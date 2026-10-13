// Trusted test fixtures: database assertions and the real identity-operator CLI.
//
// - `ownerQuery` reads (or seeds) the disposable database as its owner, for
//   assertions the application must never be able to make (it bypasses RLS).
// - `runtimeQuery` runs SQL as the API's own RLS-restricted login, to prove
//   what the database itself allows that role.
// - `operator` runs `scripts.manage_identities` exactly as the Technical Lead
//   would (revoke, suspend, set-role, bind-identity, confirm-jurisdiction, ...),
//   so lifecycle changes go through the audited, trusted procedure.
//
// All of it targets only the run's own throwaway container (checked by label).
import { execFile, spawn } from "node:child_process";

export function createFixtures({ container, database, owner, runtimeLogin, repoRoot, operatorUrl, reference = "E2E-1" }) {
  async function psql(user, sql) {
    const child = execFile(
      "docker",
      ["exec", "-i", container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-F", "\t", "-U", user, "-d", database, "-f", "-"],
      { maxBuffer: 16 * 1024 * 1024 },
    );
    const done = new Promise((resolve, reject) => {
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (chunk) => (stdout += chunk));
      child.stderr.on("data", (chunk) => (stderr += chunk));
      child.on("close", (code) => (code === 0 ? resolve(stdout) : reject(Object.assign(new Error("psql failed"), { stderr }))));
    });
    child.stdin.end(sql);
    const stdout = await done;
    return stdout.trimEnd() === "" ? [] : stdout.trimEnd().split("\n").map((line) => line.split("\t"));
  }

  return {
    /** Rows as arrays of strings (owner: bypasses RLS; for assertions and seeding only). */
    ownerQuery: (sql) => psql(owner, sql),
    async ownerValue(sql) {
      const rows = await psql(owner, sql);
      return rows[0]?.[0] ?? null;
    },
    /**
     * One statement as the API runtime login, in its own transaction, optionally
     * with a candidate tenant context set first (transaction-local, exactly as
     * the API sets it). Errors are returned, not thrown.
     */
    async runtimeQuery(sql, { company } = {}) {
      if (company !== undefined && !/^[0-9a-f-]{36}$/.test(company)) throw new Error("company must be a UUID");
      const script = [
        "BEGIN;",
        ...(company ? ["\\o /dev/null", `SELECT set_config('heroos.company_id', '${company}', true);`, "\\o"] : []),
        `${sql};`,
        "ROLLBACK;",
      ].join("\n");
      try {
        return { ok: true, rows: await psql(runtimeLogin, script) };
      } catch (error) {
        const match = /ERROR:\s+(.*)/.exec(String(error.stderr ?? error.message));
        return { ok: false, error: match ? match[1] : "error" };
      }
    },
    /**
     * Runs the operator CLI. `subject` (if any) goes to standard input, as the
     * runbook requires. Resolves to the parsed JSON result, or { error }.
     */
    operator(args, subject) {
      return new Promise((resolve) => {
        const child = spawn(
          "uv",
          ["run", "--frozen", "--quiet", "python", "-m", "scripts.manage_identities",
            "--expect-database", database, "--reference", reference, ...args],
          {
            cwd: `${repoRoot}/apps/api`,
            env: { PATH: process.env.PATH, HOME: process.env.HOME, HEROOS_OPERATOR_DATABASE_URL: operatorUrl },
            stdio: ["pipe", "pipe", "pipe"],
          },
        );
        let out = "";
        let err = "";
        child.stdout.on("data", (chunk) => (out += chunk));
        child.stderr.on("data", (chunk) => (err += chunk));
        child.stdin.end(subject === undefined ? "" : `${subject}\n`);
        child.on("close", (code) => {
          try {
            resolve({ code, ...JSON.parse(out.trim().split("\n").pop()) });
          } catch {
            resolve({ code, error: err.trim().split("\n").pop() ?? "operator failed" });
          }
        });
      });
    },
  };
}
