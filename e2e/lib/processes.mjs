// The real application processes of one end-to-end run.
//
// - API: the FastAPI app under Uvicorn (HTTPS), HEROOS_ENV=staging, the OIDC
//   provider pointed at the local test issuer, connected as the RLS-restricted
//   runtime login. Started from an empty working directory so no .env file can
//   leak in.
// - Web: the Next.js standalone server (the production build the container
//   image runs) behind a local TLS terminator, so the browser sees an https
//   origin exactly as in deployment.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createWriteStream, readFileSync } from "node:fs";
import { request as httpRequest } from "node:http";
import { createServer } from "node:https";
import { join } from "node:path";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function waitForHttp(url, { timeout = 90_000, process: child } = {}) {
  const start = Date.now();
  for (;;) {
    if (child && child.exitCode !== null) throw new Error(`process exited (${child.exitCode}) before ${url} was ready`);
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status < 500) return;
    } catch {
      // not up yet
    }
    if (Date.now() - start > timeout) throw new Error(`timeout waiting for ${url}`);
    await sleep(250);
  }
}

function startLogged(command, args, { cwd, env, logFile }) {
  const log = createWriteStream(logFile, { flags: "a" });
  // Own process group: signals reach the whole tree (e.g. uv and the Python
  // interpreter it starts), never this runner.
  const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"], detached: true });
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  return child;
}

function signalGroup(child, signal) {
  try {
    process.kill(-child.pid, signal);
  } catch {
    // already gone
  }
}

async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  signalGroup(child, "SIGCONT");
  signalGroup(child, "SIGTERM");
  for (let i = 0; i < 50 && child.exitCode === null; i += 1) await sleep(100);
  if (child.exitCode === null) signalGroup(child, "SIGKILL");
  for (let i = 0; i < 20 && child.exitCode === null; i += 1) await sleep(100);
}

/** The synthetic rule bundle's path and pin (tests only; never a real bundle). */
export function syntheticRules(repoRoot) {
  const path = join(repoRoot, "apps/api/tests/fixtures/rule_bundles/synthetic-disciplinary.json");
  return {
    HEROOS_RULE_BUNDLE_PATH: path,
    HEROOS_RULE_BUNDLE_SHA256: createHash("sha256").update(readFileSync(path)).digest("hex"),
  };
}

/** The synthetic template bundle's path and pin (M2-04C; tests only, bound to the synthetic rules). */
export function syntheticTemplates(repoRoot) {
  const path = join(repoRoot, "apps/api/tests/fixtures/template_bundles/synthetic-disciplinary.json");
  return {
    HEROOS_TEMPLATE_BUNDLE_PATH: path,
    HEROOS_TEMPLATE_BUNDLE_SHA256: createHash("sha256").update(readFileSync(path)).digest("hex"),
  };
}

/**
 * An API process. `apiDir` defaults to this checkout's apps/api; the migration
 * suite points it at an exported older revision (git archive) to run the API
 * generation a deployment step expects.
 */
export function createApi({ repoRoot, runDir, port, tls, issuer, audience, clientIds, databaseUrl, apiDir = join(repoRoot, "apps/api"), label = "api" }) {
  let child = null;
  let generation = 0;
  const api = {
    url: `https://localhost:${port}`,
    logFiles: [],
    async start({ selfRegistration = true, rules = true, templates = rules, extraEnv = {} } = {}) {
      generation += 1;
      const logFile = join(runDir, `${label}-${generation}.log`);
      api.logFiles.push(logFile);
      child = startLogged(
        "uv",
        ["run", "--frozen", "--quiet", "--project", apiDir,
          "uvicorn", "app.main:app", "--app-dir", apiDir,
          "--host", "127.0.0.1", "--port", String(port),
          "--ssl-certfile", tls.cert, "--ssl-keyfile", tls.key, "--no-access-log"],
        {
          cwd: runDir,
          logFile,
          env: {
            PATH: process.env.PATH,
            HOME: process.env.HOME,
            ...(process.env.UV_CACHE_DIR ? { UV_CACHE_DIR: process.env.UV_CACHE_DIR } : {}),
            HEROOS_ENV: "staging",
            HEROOS_LOG_LEVEL: "INFO",
            HEROOS_AUTH_PROVIDER: "oidc",
            HEROOS_OIDC_ISSUER: issuer,
            HEROOS_OIDC_AUDIENCE: audience,
            HEROOS_OIDC_CLIENT_IDS: clientIds.join(","),
            HEROOS_SELF_REGISTRATION_ENABLED: selfRegistration ? "true" : "false",
            // The harness holds synthetic data only: the sensitive screening may
            // be collected (deployed environments default to disabled).
            HEROOS_SENSITIVE_SCREENING: "synthetic_demo",
            // The fictional synthetic workflow rules (M2-03), installed the way a
            // deployment installs the private bundle: a path and its pinned SHA-256.
            // Older API generations (migration suite) ignore both.
            ...(rules ? syntheticRules(repoRoot) : {}),
            // The fictional synthetic templates (M2-04C), bound to those rules and
            // installed the same way. Older API generations ignore them too.
            ...(rules && templates ? syntheticTemplates(repoRoot) : {}),
            DATABASE_URL: databaseUrl,
            // Trust only this run's CA for the OIDC discovery and JWKS fetches.
            SSL_CERT_FILE: tls.ca,
            ...extraEnv,
            // Last, so no suite can undo them: this API is an automated test run,
            // so it never calls a real AI provider whatever gateway, demo or key
            // settings a suite passes (apps/api/app/assistant/live.py).
            HEROOS_AUTOMATED_TEST: "true",
            HEROOS_AI_LIVE_SMOKE_ENABLED: "false",
          },
        },
      );
      await waitForHttp(`${api.url}/health`, { process: child });
    },
    /** Starts and expects the process to refuse to serve; resolves to its log. */
    async startExpectingRefusal(options) {
      try {
        await api.start(options);
      } catch {
        return readFileSync(api.logFiles.at(-1), "utf8");
      }
      await api.stop();
      return null;
    },
    async stop() {
      await stopProcess(child);
      child = null;
    },
    /** Freezes the API process (SIGSTOP) to make it time out; `resume()` undoes it. */
    freeze() {
      if (child) signalGroup(child, "SIGSTOP");
    },
    resume() {
      if (child) signalGroup(child, "SIGCONT");
    },
    logs() {
      return api.logFiles.map((file) => readFileSync(file, "utf8")).join("\n");
    },
  };
  return api;
}

export function createWeb({ repoRoot, runDir, port, publicPort, tls, issuer, clientId, audience, apiUrl, sessionSecret }) {
  let child = null;
  let proxy = null;
  const logFile = join(runDir, "web.log");
  const web = {
    origin: `https://localhost:${publicPort}`,
    /** When set, HTML responses carry this Cache-Control instead (simulates a hosting platform). */
    htmlCacheControl: null,
    async start() {
      child = startLogged("node", [join(repoRoot, "apps/web/.next/standalone/apps/web/server.js")], {
        cwd: runDir,
        logFile,
        env: {
          PATH: process.env.PATH,
          NODE_ENV: "production",
          HOSTNAME: "127.0.0.1",
          PORT: String(port),
          NEXT_TELEMETRY_DISABLED: "1",
          HEROOS_WEB_ORIGIN: web.origin,
          HEROOS_WEB_AUTH_PROVIDER: "oidc",
          HEROOS_OIDC_ISSUER: issuer,
          HEROOS_OIDC_CLIENT_ID: clientId,
          HEROOS_OIDC_AUDIENCE: audience,
          HEROOS_API_BASE_URL: apiUrl,
          HEROOS_WEB_SESSION_SECRET: sessionSecret,
          NODE_EXTRA_CA_CERTS: tls.ca,
        },
      });
      // TLS terminator: the browser talks https to the public port.
      proxy = createServer({ cert: readFileSync(tls.cert), key: readFileSync(tls.key) }, (req, res) => {
        const upstream = httpRequest(
          { host: "127.0.0.1", port, method: req.method, path: req.url, headers: req.headers },
          (response) => {
            let headers = response.rawHeaders;
            // Platform simulation (opt-in): the Cache-Control the live Vercel
            // deployment was observed to send for HTML pages.
            if (web.htmlCacheControl && /text\/html/.test(response.headers["content-type"] ?? "")) {
              headers = [];
              for (let i = 0; i < response.rawHeaders.length; i += 2) {
                if (response.rawHeaders[i].toLowerCase() !== "cache-control") headers.push(response.rawHeaders[i], response.rawHeaders[i + 1]);
              }
              headers.push("Cache-Control", web.htmlCacheControl);
            }
            res.writeHead(response.statusCode, headers);
            response.pipe(res);
          },
        );
        upstream.on("error", () => {
          res.writeHead(502);
          res.end();
        });
        req.pipe(upstream);
      });
      await new Promise((resolve) => proxy.listen(publicPort, "127.0.0.1", resolve));
      await waitForHttp(`${web.origin}/`, { process: child });
    },
    async stop() {
      await stopProcess(child);
      await new Promise((resolve) => (proxy ? proxy.close(() => resolve()) : resolve()));
    },
    logs() {
      return readFileSync(logFile, "utf8");
    },
  };
  return web;
}
