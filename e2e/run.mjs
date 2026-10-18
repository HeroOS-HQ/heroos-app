// End-to-end runner. Started by scripts/verify-e2e.sh, which provides the
// disposable database, migrated schema and logins through E2E_* variables.
import { createCipheriv, createHash, hkdfSync, randomBytes, X509Certificate } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { launchBrowser } from "./lib/cdp.mjs";
import { createFixtures } from "./lib/fixtures.mjs";
import { TestIssuer } from "./lib/oidc-issuer.mjs";
import { createApi, createWeb } from "./lib/processes.mjs";
import { createReport } from "./lib/report.mjs";

const env = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set (run scripts/verify-e2e.sh)`);
  return value;
};

const repoRoot = env("E2E_REPO_ROOT");
const runDir = env("E2E_RUN_DIR");
const outputDir = env("E2E_OUTPUT_DIR");
const runId = env("E2E_RUN_ID");
const tls = { ca: join(runDir, "tls/ca.pem"), cert: join(runDir, "tls/server.pem"), key: join(runDir, "tls/server-key.pem") };
const AUDIENCE = "https://api.heroos.e2e.test";
const CLIENT_ID = "heroos-e2e-web";
const OTHER_CLIENT_ID = "heroos-e2e-other-app";
const webPort = Number(env("E2E_WEB_PORT"));
const webOrigin = `https://localhost:${webPort}`;
const sessionSecret = env("E2E_SESSION_SECRET");

const report = createReport();
const issuer = new TestIssuer({
  port: Number(env("E2E_ISSUER_PORT")),
  tls,
  audience: AUDIENCE,
  clients: {
    [CLIENT_ID]: { redirectUris: [`${webOrigin}/auth/callback`], postLogoutRedirectUris: [`${webOrigin}/`] },
    // A second client of the same issuer: its tokens must not be accepted by the API.
    [OTHER_CLIENT_ID]: { redirectUris: ["https://other.example/callback"], postLogoutRedirectUris: [] },
  },
});

// A second provider (an M5-style cut-over: the same person, another issuer).
const secondIssuer = new TestIssuer({
  port: Number(env("E2E_ISSUER2_PORT")),
  tls,
  audience: AUDIENCE,
  clients: { [CLIENT_ID]: { redirectUris: [`${webOrigin}/auth/callback`], postLogoutRedirectUris: [`${webOrigin}/`] } },
});

// Every access token and session minted in this run, to prove none reaches a log.
const issuedTokens = [];
const issuedSessions = [];
const mint = issuer.accessToken.bind(issuer);
issuer.accessToken = (...args) => {
  const token = mint(...args);
  issuedTokens.push(token);
  return token;
};

const dbPort = env("E2E_DB_PORT");
const urls = {
  owner: (db) => `postgresql+psycopg://${env("E2E_OWNER")}:${env("E2E_OWNER_PASSWORD")}@127.0.0.1:${dbPort}/${db}`,
  // 127.0.0.2: the API runs with HEROOS_ENV=staging, which refuses local development host names.
  runtime: (db) => `postgresql+psycopg://${env("E2E_RUNTIME_LOGIN")}:${env("E2E_RUNTIME_PASSWORD")}@127.0.0.2:${dbPort}/${db}`,
  operator: (db) => `postgresql+psycopg://${env("E2E_OPERATOR_LOGIN")}:${env("E2E_OPERATOR_PASSWORD")}@127.0.0.1:${dbPort}/${db}`,
};
const makeFixtures = (database) =>
  createFixtures({
    container: env("E2E_CONTAINER"),
    database,
    owner: env("E2E_OWNER"),
    runtimeLogin: env("E2E_RUNTIME_LOGIN"),
    repoRoot,
    operatorUrl: urls.operator(database),
  });
const fixtures = makeFixtures(env("E2E_DATABASE"));

const api = createApi({
  repoRoot,
  runDir,
  port: Number(env("E2E_API_PORT")),
  tls,
  issuer: issuer.issuer,
  audience: AUDIENCE,
  clientIds: [CLIENT_ID],
  databaseUrl: urls.runtime(env("E2E_DATABASE")),
});

const web = createWeb({
  repoRoot,
  runDir,
  port: Number(env("E2E_WEB_INTERNAL_PORT")),
  publicPort: webPort,
  tls,
  issuer: issuer.issuer,
  clientId: CLIENT_ID,
  audience: AUDIENCE,
  apiUrl: api.url,
  sessionSecret,
});

/** apps/web/src/lib/server/sealed.ts, for forging expired or tampered cookies in negative tests. */
function seal(payload, purpose) {
  const key = Buffer.from(hkdfSync("sha256", Buffer.from(sessionSecret, "hex"), Buffer.alloc(0), `heroos-web/${purpose}`, 32));
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(purpose));
  const body = Buffer.concat([cipher.update(JSON.stringify(payload), "utf8"), cipher.final()]);
  return ["v1", iv, body, cipher.getAuthTag()].map((p) => (typeof p === "string" ? p : p.toString("base64url"))).join(".");
}

const spki = (pemFile) =>
  createHash("sha256").update(new X509Certificate(readFileSync(pemFile)).publicKey.export({ type: "spki", format: "der" })).digest("base64");

async function readResponse(response) {
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // not JSON
  }
  return { status: response.status, headers: response.headers, text, json };
}

const ctx = {
  repoRoot,
  runDir,
  outputDir,
  runId,
  report,
  check: report.check,
  issuer,
  secondIssuer,
  fixtures,
  api,
  web,
  webOrigin,
  AUDIENCE,
  CLIENT_ID,
  OTHER_CLIENT_ID,
  seal,
  urls,
  makeFixtures,
  container: env("E2E_CONTAINER"),
  owner: env("E2E_OWNER"),
  /** Another API process (another database or an older exported revision). */
  makeApi: (options) =>
    createApi({ repoRoot, runDir, tls, issuer: issuer.issuer, audience: AUDIENCE, clientIds: [CLIENT_ID], port: Number(env("E2E_API2_PORT")), ...options }),
  issuedTokens,
  issuedSessions,
  /** A valid access token for `subject` from the test provider. */
  token: (subject, options) => issuer.accessToken(subject, options),
  /** A unique, synthetic external subject for this run (Auth0-like shape). */
  subject: (name) => `e2e|${runId}-${name}`,
  /** Direct call to the API, as only the web server should ever make it. */
  async apiFetch(path, { token, method = "GET", body, headers = {} } = {}) {
    const response = await fetch(`${api.url}${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
      redirect: "manual",
    });
    return readResponse(response);
  },
  /** A request to the web server as an arbitrary (possibly hostile) client. */
  async webFetch(path, { method = "GET", headers = {}, body, session } = {}) {
    const cookie = session ? `__Host-heroos-session=${session}` : undefined;
    const response = await fetch(`${webOrigin}${path}`, {
      method,
      headers: { ...(cookie ? { Cookie: cookie } : {}), ...headers },
      body,
      redirect: "manual",
    });
    return readResponse(response);
  },
  /** A sealed web session holding `token` (the same cookie a real sign-in sets). */
  session(token, { expiresIn = 600 } = {}) {
    const sealed = seal({ accessToken: token, exp: Math.floor(Date.now() / 1000) + expiresIn }, "session");
    issuedSessions.push(sealed);
    return sealed;
  },
  async newPage() {
    return ctx.browser.newPage();
  },
  /** Signs in (or signs up) in the browser through the hosted page of the test provider. */
  async signIn(page, subject, { signup = false } = {}) {
    await page.goto(`${webOrigin}/auth/${signup ? "signup" : "login"}`);
    await page.waitFor(`location.origin === ${JSON.stringify(issuer.origin)} && document.getElementById("subject")`, {
      message: "hosted sign-in page",
    });
    await page.type("#subject", subject);
    await page.click("#continue");
    await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && document.readyState === "complete"`, {
      message: "back on the web app",
    });
    // The landing ("/" then "/workspaces") streams its content and may still
    // redirect on the client (a server redirect inside Suspense, e.g. to the only
    // workspace), sometimes without ever showing the loading fallback. It has
    // settled once it left those paths, or once it shows a page heading (the
    // workspace chooser or a state view) instead of the loading fallback;
    // otherwise that redirect can overtake the test's next navigation.
    await page.waitFor(
      `document.readyState === "complete" && document.body && !document.body.innerText.includes("Loading your workspace") &&
        (!["/", "/workspaces"].includes(location.pathname) || Boolean(document.querySelector("h1")))`,
      { message: "landing page settled" },
    );
  },
  async screenshot(page, name) {
    await page.screenshot(join(outputDir, "screenshots", `${name}.png`));
  },
  /** A screenshot of one element of the page (e.g. a section further down a long page). */
  async screenshotOf(page, name, selector) {
    await page.screenshotOf(join(outputDir, "screenshots", `${name}.png`), selector);
  },
  sleep: (ms) => new Promise((done) => setTimeout(done, ms)),
};

const SUITES = ["api-auth", "registration", "isolation", "jurisdiction", "bff", "browser", "cases", "intake", "progression", "decisions", "migration"];
const selected = process.env.E2E_SUITES ? process.env.E2E_SUITES.split(",") : SUITES;

let exitCode = 1;
try {
  mkdirSync(join(outputDir, "screenshots"), { recursive: true });
  report.section("setup");
  await issuer.start();
  await secondIssuer.start();
  await api.start();
  await web.start();
  ctx.browser = await launchBrowser({ port: Number(env("E2E_CHROME_PORT")), caCertificateSpki: [spki(tls.cert), spki(tls.ca)].join(",") });
  report.check("SETUP-1", "issuer, API (staging, OIDC) and web (standalone, TLS) are up", true);

  for (const name of SUITES.filter((suite) => selected.includes(suite))) {
    report.section(name);
    const suite = await import(`./suites/${name}.mjs`);
    try {
      await suite.run(ctx);
    } catch (error) {
      report.check(`${name.toUpperCase()}-ERR`, `suite ${name} completed without an unexpected error`, false, error.stack ?? String(error));
    }
  }

  report.section("logs");
  // Credentials must never reach logs: no access token issued in this run may appear.
  const logs = `${api.logs()}\n${web.logs()}`;
  const leaked = issuedTokens.filter((token) => logs.includes(token));
  // Signatures of unsigned tokens are empty: only real signatures are searched for.
  report.check("LOG-1", `none of the ${issuedTokens.length} access tokens of this run appears in the API or web logs`, issuedTokens.length > 0 && leaked.length === 0, `${leaked.length} leaked`);
  report.check("LOG-2", "no session cookie value appears in the server logs", !issuedSessions.some((s) => logs.includes(s)));
  const signatures = issuedTokens.map((token) => token.split(".")[2]).filter((s) => s && s.length > 20 && logs.includes(s));
  report.check("LOG-3", "no token signature fragment appears in the logs", signatures.length === 0);
  // External subjects are pseudonymous personal data (ADR-008): never logged.
  report.check("LOG-4", "no external subject of this run appears in the API or web logs", !logs.includes(`e2e|${runId}`));
  exitCode = report.failed.length === 0 ? 0 : 1;
} catch (error) {
  report.check("SETUP-ERR", "harness completed without an unexpected error", false, error.stack ?? String(error));
} finally {
  await ctx.browser?.close().catch(() => {});
  await web.stop().catch(() => {});
  await api.stop().catch(() => {});
  await issuer.stop().catch(() => {});
  await secondIssuer.stop().catch(() => {});
  const summary = report.write(outputDir, { runId, finishedAt: new Date().toISOString() });
  console.log(`\n${summary.passed} passed, ${summary.failed} failed, ${summary.notRun} not run (of ${summary.total}).`);
  process.exit(exitCode);
}
