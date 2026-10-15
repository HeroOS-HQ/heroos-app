// Phase H: the staging transition rehearsed on a disposable copy, in the
// runbook's order, with the real Alembic CLI, the real operator CLI and the
// API generations each deployment step expects (exported with `git archive`,
// run as real processes against the same database):
//
//   pre-M1-10B API (371dd50) on the demo schema (97d4200fe7a2)
//   -> backup -> B1a (guarded arguments) -> M1-10B API (169261d) -> B1b -> C1
//   -> M1-10C API (2f0fad8) -> D1 (M2-01 workflow tables) -> M2-01 API (e4378f7)
//   -> D2 (M2-02 intake evaluations) -> current API
//   -> appoint administrators -> downgrade guards
//   -> backup/restore of the D2 database and of the pre-B1a backup.
//
// Nothing here touches the main end-to-end database.
import { execFile, spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);
const PRE_B1 = "97d4200fe7a2";
const B1A = "b8a11c15ed91";
const B1B = "09cb5ec569b9";
const C1 = "3f6c2a9d81b4";
const D1 = "75ec6db8b6c1";
const D2 = "e64497d997d8";
// The last API generation before D1 (M1-10C roles and jurisdiction readiness).
const M110C_API = "2f0fad8";
// The last API generation before D2 (M2-01 workflow Cases, contract >= 4).
const M201_API = "e4378f7";
const A = "d3e0a000-0000-4000-8000-0000000000e1";
const B = "d3e0b000-0000-4000-8000-0000000000e1";
const USER_A = "d3e0a000-0000-4000-8000-00000000a0e1";
const USER_B = "d3e0b000-0000-4000-8000-00000000b0e1";

export async function run(ctx) {
  const { check } = ctx;
  const stage = "heroos_stage";
  const subjects = { alpha: ctx.subject("demo-alpha"), beta: ctx.subject("demo-beta") };
  const tokens = { alpha: ctx.token(subjects.alpha), beta: ctx.token(subjects.beta) };
  const docker = (...args) => exec("docker", ["exec", "-i", ctx.container, ...args], { maxBuffer: 64 * 1024 * 1024 });
  const alembic = (database, ...args) =>
    new Promise((resolve) => {
      const child = spawn("uv", ["run", "--frozen", "--quiet", "alembic", ...args], {
        cwd: join(ctx.repoRoot, "apps/api"),
        env: { PATH: process.env.PATH, HOME: process.env.HOME, MIGRATION_DATABASE_URL: ctx.urls.owner(database) },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let err = "";
      child.stderr.on("data", (c) => (err += c));
      child.stdout.on("data", () => {});
      child.on("close", (code) => resolve({ code, err }));
    });
  const db = ctx.makeFixtures(stage);
  const revision = () => db.ownerValue("SELECT version_num FROM alembic_version");
  const contract = () => db.ownerValue("SELECT heroos_schema_contract()");
  const probe = async (api, who, company) =>
    (await fetch(`${api.url}/companies/${company}`, { headers: { Authorization: `Bearer ${tokens[who]}` } })).status;
  const exportRevision = async (rev) => {
    const dir = join(ctx.runDir, "old-api", rev);
    mkdirSync(dir, { recursive: true });
    await exec("bash", ["-c", `git -C "$0" archive "$1" apps/api | tar -x -C "$2"`, ctx.repoRoot, rev, dir]);
    return join(dir, "apps/api");
  };

  // --- the demo schema with demo-like synthetic data -----------------------------
  await docker("createdb", "-U", ctx.owner, stage);
  const pre = await alembic(stage, "upgrade", PRE_B1);
  check("MIG-1", `a disposable database at the pre-M1-10B revision (${PRE_B1})`, pre.code === 0 && (await revision()) === PRE_B1, pre.err.slice(-300));
  await db.ownerQuery(`
    INSERT INTO companies (id, name) VALUES ('${A}', '[SYNTHETIC DEMO] Alpha'), ('${B}', '[SYNTHETIC DEMO] Beta');
    INSERT INTO users (id, identity_subject) VALUES ('${USER_A}', '${subjects.alpha}'), ('${USER_B}', '${subjects.beta}');
    INSERT INTO memberships (id, company_id, user_id) VALUES (gen_random_uuid(), '${A}', '${USER_A}'), (gen_random_uuid(), '${B}', '${USER_B}');
    INSERT INTO company_blueprints (id, company_id, legal_name, primary_jurisdiction, industry, employee_count)
      VALUES (gen_random_uuid(), '${A}', 'Alpha Demo LLC', 'DIFC', 'Retail', 12);
    INSERT INTO cases (id, company_id, case_type, title) VALUES
      (gen_random_uuid(), '${A}', 'probation', '[SYNTHETIC DEMO] Case A'), (gen_random_uuid(), '${B}', 'probation', '[SYNTHETIC DEMO] Case B');
  `);
  const seedSnapshot = await db.ownerQuery("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM cases), (SELECT count(*) FROM company_blueprints)");

  const legacyDir = await exportRevision("371dd50");
  const legacyApi = ctx.makeApi({ apiDir: legacyDir, databaseUrl: ctx.urls.runtime(stage), label: "api-371dd50" });
  await legacyApi.start();
  check("MIG-2", "the pre-M1-10B API (371dd50) serves the demo: own Company 200, the other 403",
    (await probe(legacyApi, "alpha", A)) === 200 && (await probe(legacyApi, "alpha", B)) === 403 && (await probe(legacyApi, "beta", B)) === 200);

  // --- step 1: backup ---------------------------------------------------------------
  await docker("pg_dump", "-U", ctx.owner, "-Fc", "-f", "/tmp/stage-pre-b1a.dump", stage);
  check("MIG-3", "a logical backup of the pre-B1a database is taken (custom format)", true);

  // --- step 2: B1a, guarded ---------------------------------------------------------------
  const wrongCount = await alembic(stage, "-x", `legacy_identity_issuer=${ctx.issuer.issuer}`, "-x", "legacy_identity_user_count=3", "upgrade", B1A);
  check("MIG-4", "B1a refuses a wrong legacy_identity_user_count and leaves the schema unchanged", wrongCount.code !== 0 && (await revision()) === PRE_B1, wrongCount.err.split("\n").filter((l) => /Error|refus/i.test(l)).slice(-1)[0]);
  const noIssuer = await alembic(stage, "-x", "legacy_identity_user_count=2", "upgrade", B1A);
  check("MIG-5", "B1a refuses to run without the legacy issuer argument", noIssuer.code !== 0 && (await revision()) === PRE_B1);
  const b1a = await alembic(stage, "-x", `legacy_identity_issuer=${ctx.issuer.issuer}`, "-x", "legacy_identity_user_count=2", "upgrade", B1A);
  const bindings = await db.ownerQuery(`SELECT user_id, issuer, subject, status FROM user_identities ORDER BY subject`);
  check("MIG-6", "B1a binds each existing User under the exact issuer with its existing subject (contract 1)",
    b1a.code === 0 && (await contract()) === "1" && bindings.length === 2 &&
    bindings.every((r) => r[1] === ctx.issuer.issuer && r[3] === "active") && bindings.map((r) => r[2]).sort().join() === [subjects.alpha, subjects.beta].sort().join(), JSON.stringify(bindings));
  check("MIG-7", "the pre-M1-10B API keeps working on B1a (expand step)", (await probe(legacyApi, "alpha", A)) === 200 && (await probe(legacyApi, "alpha", B)) === 403);
  await legacyApi.stop();
  const currentOnStage = ctx.makeApi({ databaseUrl: ctx.urls.runtime(stage), label: "api-current-stage" });
  const refusedB1a = await currentOnStage.startExpectingRefusal();
  check("MIG-8", "the current API refuses to start on B1a (schema contract 1 < 5)", refusedB1a !== null && /contract is 1/.test(refusedB1a), (refusedB1a ?? "started!").split("\n").filter((l) => /contract/.test(l)).slice(-1)[0]);

  // --- step 3: the M1-10B API ------------------------------------------------------------------
  const m110bDir = await exportRevision("169261d");
  const m110bApi = ctx.makeApi({ apiDir: m110bDir, databaseUrl: ctx.urls.runtime(stage), label: "api-169261d" });
  await m110bApi.start();
  check("MIG-9", "the M1-10B API (169261d) starts on B1a and authorizes through the new bindings", (await probe(m110bApi, "alpha", A)) === 200 && (await probe(m110bApi, "beta", A)) === 403);

  // --- step 4: B1b -------------------------------------------------------------------------------
  const b1b = await alembic(stage, "upgrade", B1B);
  check("MIG-10", "B1b applies (contract 2) and the M1-10B API keeps working", b1b.code === 0 && (await contract()) === "2" && (await probe(m110bApi, "alpha", A)) === 200);
  await m110bApi.stop();
  const legacyAfterB1b = await legacyApi.startExpectingRefusal().then(async (log) => {
    if (log !== null) return { refused: true, status: null };
    await legacyApi.start();
    const status = await probe(legacyApi, "alpha", A);
    await legacyApi.stop();
    return { refused: false, status };
  });
  check("MIG-11", "the pre-M1-10B API fails closed on B1b (never serves data): refuses to start or answers non-200",
    legacyAfterB1b.refused || legacyAfterB1b.status !== 200, JSON.stringify(legacyAfterB1b));
  const refusedB1b = await currentOnStage.startExpectingRefusal();
  check("MIG-12", "the current API still refuses on B1b (contract 2 < 5)", refusedB1b !== null && /contract is 2/.test(refusedB1b));

  // --- step 5: C1 --------------------------------------------------------------------------------
  const c1 = await alembic(stage, "upgrade", C1);
  check("MIG-13", "C1 applies (contract 3)", c1.code === 0 && (await contract()) === "3", c1.err.slice(-300));
  await m110bApi.start();
  check("MIG-14", "the M1-10B API keeps working on C1 (deploy order tolerance)", (await probe(m110bApi, "alpha", A)) === 200 && (await probe(m110bApi, "alpha", B)) === 403);
  await m110bApi.stop();
  const preserved = await db.ownerQuery("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM cases)");
  check("MIG-15", "Companies, Users, Memberships and cases survive the whole transition", JSON.stringify(preserved[0]) === JSON.stringify(seedSnapshot[0].slice(0, 4)), `${JSON.stringify(seedSnapshot)} -> ${JSON.stringify(preserved)}`);
  const roles = await db.ownerQuery("SELECT DISTINCT role FROM memberships");
  check("MIG-16", "every existing Membership became member: no administrator was created by the migration", roles.length === 1 && roles[0][0] === "member");
  const blueprints = await db.ownerQuery(`SELECT company_id, coalesce(legal_name, '-'), coalesce(employment_jurisdiction, '-'), coalesce(licensing_location, '-') FROM company_blueprints ORDER BY company_id`);
  check("MIG-17", "Alpha's Blueprint data is preserved; Beta (which had none) got an empty Blueprint; nothing is confirmed",
    blueprints.length === 2 && blueprints[0][1] === "Alpha Demo LLC" && blueprints[1][1] === "-" && blueprints.every((b) => b[2] === "-" && b[3] === "-"), JSON.stringify(blueprints));

  // --- step 6: the M1-10C API on C1 (the generation that runs before M2) ----------------------
  const refusedC1 = await currentOnStage.startExpectingRefusal();
  check("MIG-30", "the current API refuses to start on C1 (schema contract 3 < 5)", refusedC1 !== null && /contract is 3/.test(refusedC1), (refusedC1 ?? "started!").split("\n").filter((l) => /contract/.test(l)).slice(-1)[0]);
  const m110cDir = await exportRevision(M110C_API);
  const m110cApi = ctx.makeApi({ apiDir: m110cDir, databaseUrl: ctx.urls.runtime(stage), label: `api-${M110C_API}` });
  await m110cApi.start();
  const discovery = await (await fetch(`${m110cApi.url}/me/companies`, { headers: { Authorization: `Bearer ${tokens.alpha}` } })).json();
  const readiness = await (await fetch(`${m110cApi.url}/companies/${A}/blueprint`, { headers: { Authorization: `Bearer ${tokens.alpha}` } })).json();
  check("MIG-18", "the M1-10C API on C1: the demo user discovers its Company as member", discovery.length === 1 && discovery[0].company_id === A && discovery[0].role === "member");
  check("MIG-19", "the legacy primary_jurisdiction \"DIFC\" is not turned into a confirmed jurisdiction (unconfirmed, no guidance)",
    readiness.jurisdiction?.readiness === "unconfirmed" && readiness.jurisdiction?.guidance_allowed === false && readiness.legal_name === "Alpha Demo LLC");
  const beforeAppoint = await fetch(`${m110cApi.url}/companies/${A}/blueprint`, { method: "PATCH", headers: { Authorization: `Bearer ${tokens.alpha}`, "Content-Type": "application/json" }, body: JSON.stringify({ industry: "Retail and services" }) });
  check("MIG-20", "before appointment the demo user cannot administer (403)", beforeAppoint.status === 403);
  check("MIG-21", "cross-tenant access stays denied after the transition", (await probe(m110cApi, "alpha", B)) === 403 && (await probe(m110cApi, "beta", A)) === 403);

  // --- step 7: D1 (M2-01 workflow tables), then the current API --------------------------------
  const d1 = await alembic(stage, "upgrade", D1);
  const afterD1 = await db.ownerQuery("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM cases)");
  check("MIG-31", "D1 applies (contract 4) and leaves existing data unchanged", d1.code === 0 && (await contract()) === "4" && JSON.stringify(afterD1) === JSON.stringify(preserved), d1.err.slice(-300));
  check("MIG-32", "the M1-10C API keeps working on D1 (migrate first, then deploy the API)", (await probe(m110cApi, "alpha", A)) === 200 && (await probe(m110cApi, "alpha", B)) === 403);
  await m110cApi.stop();
  const refusedD1 = await currentOnStage.startExpectingRefusal();
  check("MIG-36", "the current API refuses to start on D1 (schema contract 4 < 5)", refusedD1 !== null && /contract is 4/.test(refusedD1), (refusedD1 ?? "started!").split("\n").filter((l) => /contract/.test(l)).slice(-1)[0]);
  const m201Dir = await exportRevision(M201_API);
  const m201Api = ctx.makeApi({ apiDir: m201Dir, databaseUrl: ctx.urls.runtime(stage), label: `api-${M201_API}` });
  await m201Api.start();
  const m201List = async () => (await fetch(`${m201Api.url}/companies/${A}/workflows/disciplinary/cases`, { headers: { Authorization: `Bearer ${tokens.alpha}` } })).status;
  check("MIG-37", "the M2-01 API (e4378f7) serves D1: own Company 200, the other 403, Disciplinary 403 for a member", (await probe(m201Api, "alpha", A)) === 200 && (await probe(m201Api, "alpha", B)) === 403 && (await m201List()) === 403);

  // --- step 8: D2 (M2-02 intake evaluations), then the current API -----------------------------
  const d2 = await alembic(stage, "upgrade", D2);
  const afterD2 = await db.ownerQuery("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM cases)");
  check("MIG-38", "D2 applies (contract 5) and leaves existing data unchanged", d2.code === 0 && (await contract()) === "5" && JSON.stringify(afterD2) === JSON.stringify(preserved), d2.err.slice(-300));
  check("MIG-39", "the M2-01 API keeps working on D2 (migrate first, then deploy the API)", (await probe(m201Api, "alpha", A)) === 200 && (await probe(m201Api, "alpha", B)) === 403 && (await m201List()) === 403);
  await m201Api.stop();
  await currentOnStage.start();
  const workflowList = await fetch(`${currentOnStage.url}/companies/${A}/workflows/disciplinary/cases`, { headers: { Authorization: `Bearer ${tokens.alpha}` } });
  check("MIG-33", "the current API starts on D2; the not-yet-appointed demo member gets no Disciplinary access (403, administrators only)",
    workflowList.status === 403 && (await probe(currentOnStage, "alpha", A)) === 200 && (await probe(currentOnStage, "alpha", B)) === 403);

  // --- step 9: appoint administrators through the trusted procedure -------------------------
  const membershipA = await db.ownerValue(`SELECT id FROM memberships WHERE company_id = '${A}'`);
  const appointed = await db.operator(["set-role", "--company", A, "--membership", membershipA, "--role", "company_admin"]);
  const afterAppoint = await fetch(`${currentOnStage.url}/companies/${A}/blueprint`, { method: "PATCH", headers: { Authorization: `Bearer ${tokens.alpha}`, "Content-Type": "application/json" }, body: JSON.stringify({ industry: "Retail and services" }) });
  const roleEvent = await db.ownerQuery(`SELECT actor_kind, actor_reference FROM membership_events WHERE membership_id = '${membershipA}' AND event_type = 'membership_role_changed'`);
  check("MIG-22", "the operator appoints the demo administrator (audited), who can then administer", appointed.code === 0 && afterAppoint.status === 200 && roleEvent.length === 1 && roleEvent[0][0] === "operator");

  // --- rollback restrictions -------------------------------------------------------------------
  const downgrade = await alembic(stage, "downgrade", B1B);
  check("MIG-23", "C1 cannot be downgraded once a role change exists (roll forward only; the whole downgrade is refused)", downgrade.code !== 0 && (await revision()) === D2, downgrade.err.split("\n").filter((l) => /refus|Error/.test(l)).slice(-1)[0]);
  const adminList = await fetch(`${currentOnStage.url}/companies/${A}/workflows/disciplinary/cases`, { headers: { Authorization: `Bearer ${tokens.alpha}` } });
  check("MIG-35", "once appointed, the administrator sees an empty Disciplinary list (existing cases are not workflow Cases)",
    adminList.status === 200 && JSON.stringify(await adminList.json()) === "[]");
  const created = await fetch(`${currentOnStage.url}/companies/${A}/workflows/disciplinary/cases`, {
    method: "POST",
    headers: { Authorization: `Bearer ${tokens.alpha}`, "Content-Type": "application/json" },
    body: JSON.stringify({ title: "[SYNTHETIC DEMO] Workflow case", request_key: "5d1e0000-0000-4000-8000-0000000000d1" }),
  });
  const d1Down = await alembic(stage, "downgrade", C1);
  check("MIG-34", "D1 cannot be downgraded once a workflow Case exists (roll forward only; PRIV-020)",
    created.status === 201 && d1Down.code !== 0 && (await revision()) === D2 && (await db.ownerValue("SELECT count(*) FROM workflow_instances")) === "1",
    d1Down.err.split("\n").filter((l) => /refus|Error/.test(l)).slice(-1)[0]);
  // D2 holds no evaluation yet (the Case has no saved answers): reversible, then re-applied.
  const d2Down = await alembic(stage, "downgrade", D1);
  const downContract = await contract();
  const d2Up = await alembic(stage, "upgrade", D2);
  check("MIG-40", "D2 can be downgraded while no evaluation exists (contract 4) and re-applied (contract 5)",
    d2Down.code === 0 && downContract === "4" && d2Up.code === 0 && (await revision()) === D2 && (await contract()) === "5", `${d2Down.err.slice(-200)} ${d2Up.err.slice(-200)}`);
  const caseId = (await db.ownerValue("SELECT case_id FROM workflow_instances"));
  const saved = await fetch(`${currentOnStage.url}/companies/${A}/cases/${caseId}/workflow/steps/initial_facts/answers`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${tokens.alpha}`, "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: 0, submission_key: "5d2e0000-0000-4000-8000-0000000000d2", answers: { "incident.history": "new" } }),
  });
  const d2Refused = await alembic(stage, "downgrade", D1);
  check("MIG-41", "D2 cannot be downgraded once an evaluation exists (roll forward only; PRIV-020)",
    saved.status === 200 && d2Refused.code !== 0 && (await revision()) === D2 && (await db.ownerValue("SELECT count(*) FROM workflow_evaluations")) === "1",
    d2Refused.err.split("\n").filter((l) => /refus|Error/.test(l)).slice(-1)[0]);

  // --- backup and restore of the D2 database -------------------------------------------------
  const catalog = (fixture) => fixture.ownerQuery(`SELECT
      (SELECT count(*) FROM pg_policies WHERE schemaname = 'public'),
      (SELECT string_agg(c.relname || ':' || c.relrowsecurity, ',' ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'),
      (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.prosecdef),
      (SELECT string_agg(p.proname || ':' || coalesce(p.proacl::text, 'default'), ';' ORDER BY p.proname, p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'),
      (SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND NOT t.tgisinternal),
      (SELECT string_agg(table_name || ':' || privilege_type, ',' ORDER BY table_name, privilege_type) FROM information_schema.role_table_grants WHERE grantee = 'heroos_app_runtime'),
      (SELECT count(*) FROM information_schema.column_privileges WHERE grantee IN ('heroos_app_runtime', 'heroos_identity_operator')),
      (SELECT count(*) FROM company_events), (SELECT count(*) FROM membership_events), (SELECT count(*) FROM identity_events),
      (SELECT version_num FROM alembic_version), heroos_schema_contract()`);
  const sourceCatalog = await catalog(db);
  await docker("pg_dump", "-U", ctx.owner, "-Fc", "-f", "/tmp/stage-d2.dump", stage);
  // A revocation made after the backup.
  const membershipB = await db.ownerValue(`SELECT id FROM memberships WHERE company_id = '${B}'`);
  const revoked = await db.operator(["revoke-membership", "--company", B, "--membership", membershipB]);
  check("MIG-24", "after the backup, Beta's demo user is revoked (live database: 403)", revoked.code === 0 && (await probe(currentOnStage, "beta", B)) === 403);
  await currentOnStage.stop();

  await docker("createdb", "-U", ctx.owner, "heroos_stage_restored");
  const restore = await docker("pg_restore", "-U", ctx.owner, "--no-owner", "--single-transaction", "--exit-on-error", "-d", "heroos_stage_restored", "/tmp/stage-d2.dump").then(() => 0, (e) => e.stderr);
  const restored = ctx.makeFixtures("heroos_stage_restored");
  const restoredCatalog = await catalog(restored);
  check("MIG-25", "the D2 backup restores (single transaction, no owner changes)", restore === 0, String(restore).slice(0, 300));
  check("MIG-26", "RLS, policies, SECURITY DEFINER functions and their grants, triggers, table and column grants and audit rows survive the restore",
    JSON.stringify(restoredCatalog) === JSON.stringify(sourceCatalog), `${JSON.stringify(sourceCatalog).slice(0, 150)} vs ${JSON.stringify(restoredCatalog).slice(0, 150)}`);
  const restoredApi = ctx.makeApi({ databaseUrl: ctx.urls.runtime("heroos_stage_restored"), label: "api-current-restored" });
  await restoredApi.start();
  const betaRestored = await probe(restoredApi, "beta", B);
  check("MIG-27", "the restored database brings the later-revoked access back (200): the reconciliation gate is required before any cutover",
    betaRestored === 200, `beta on restored copy: ${betaRestored}`);
  check("MIG-28", "tenant isolation still holds on the restored copy", (await probe(restoredApi, "alpha", B)) === 403 && (await probe(restoredApi, "beta", A)) === 403);
  await restoredApi.stop();

  // --- restoring the pre-B1a backup (recovery from a failed window) ---------------------------
  await docker("createdb", "-U", ctx.owner, "heroos_stage_pre");
  const preRestore = await docker("pg_restore", "-U", ctx.owner, "--no-owner", "--single-transaction", "--exit-on-error", "-d", "heroos_stage_pre", "/tmp/stage-pre-b1a.dump").then(() => 0, (e) => e.stderr);
  const preDb = ctx.makeFixtures("heroos_stage_pre");
  const preRevision = await preDb.ownerValue("SELECT version_num FROM alembic_version");
  const preCounts = await preDb.ownerQuery("SELECT (SELECT count(*) FROM companies), (SELECT count(*) FROM users), (SELECT count(*) FROM memberships), (SELECT count(*) FROM cases), (SELECT count(*) FROM company_blueprints)");
  const hasSubjectColumn = await preDb.ownerValue("SELECT count(*) FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'identity_subject'");
  check("MIG-29", "the pre-B1a backup restores to the demo schema and data exactly (the fallback for a failed B1a window)",
    preRestore === 0 && preRevision === PRE_B1 && JSON.stringify(preCounts) === JSON.stringify(seedSnapshot) && hasSubjectColumn === "1");
  await docker("rm", "-f", "/tmp/stage-pre-b1a.dump", "/tmp/stage-d2.dump");
}
