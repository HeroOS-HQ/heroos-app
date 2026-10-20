// M2-01 (and M2-NEW-02's signed-in workspace): the case journey with the real
// components together (a Company whose jurisdiction isn't confirmed: the M2-02
// intake is paused; the intake itself is e2e/suites/intake.mjs).
// Browser (founder = company administrator): Ask HeroOS (the signed-in home)
// -> empty Cases drawer -> a question in the founder's own words (Send
// double-clicked) opens one case with those words saved -> answers saved ->
// reload -> sign out and in -> still there; then a member's access, another
// Company's denial, duplicate and stale writes, PostgreSQL rows and RLS, and no
// case content in any log. Synthetic data only.
import { newFounder, openFullCaseDetails, quote, signOutFromMenu } from "./common.mjs";

const NARRATIVE = "[SYNTHETIC E2E] A team member left the site early on two shifts without telling anyone.";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// Once the initial facts are complete, a case opens on the next question group
// with questions left; open "Initial facts" explicitly to see its answers.
async function openInitialFacts(page) {
  await page.waitForHydrated('nav[aria-label="Question groups"] button');
  await page.clickText("button", "1. Initial facts");
  await page.waitForHydrated("#q-incident-narrative");
}

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const founder = await newFounder(ctx, "cases-admin");
  const other = await newFounder(ctx, "cases-other");
  const memberSubject = ctx.subject("cases-member");
  const provisioned = await fixtures.operator(["provision", "--company", founder.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  const member = { subject: memberSubject, token: ctx.token(memberSubject) };
  check("CASE-0", "fixtures: two founders (administrators) and a provisioned member of the first Company", provisioned.code === 0, JSON.stringify(provisioned).slice(0, 200));

  const companyPath = `/workspaces/${founder.companyId}`;
  const casesApi = (company) => `/companies/${company}/workflows/disciplinary/cases`;
  const owner = (sql) => fixtures.ownerQuery(sql);
  const incidentDay = new Date(Date.now() - 3 * 86_400_000).toISOString().slice(0, 10);

  // ===== Browser: ask, answer, persist (1440 wide) =====
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  await ctx.signIn(page, founder.subject);
  await page.goto(`${webOrigin}${companyPath}`);
  await page.waitForText("What can HR do for you today?");
  const home = await page.eval(`({
    text: document.body.innerText,
    header: [...document.querySelectorAll("header a, header button")].map((e) => e.getAttribute("aria-label") || e.textContent.trim()),
    menu: [...document.querySelectorAll('ul[aria-label="Company"] a')].map((a) => a.getAttribute("href")),
  })`);
  check("CASE-1", "Ask HeroOS is the signed-in home: one question, no dashboard or HR Services; the account menu holds the Company Blueprint and Company Space",
    home.text.includes("Explain the situation in your own words.") && !/Dashboard|HR [Ss]ervices|Team & Access/.test(home.text) &&
      home.header.includes("Cases") && JSON.stringify(home.menu) === JSON.stringify([`${companyPath}/settings`, `${companyPath}/space`]),
    JSON.stringify(home).slice(0, 300));

  await page.waitForHydrated('button[aria-label="Cases"]');
  await page.click('button[aria-label="Cases"]');
  await page.waitForText("No cases yet");
  check("CASE-2", "an administrator's Cases drawer starts empty and points to Ask HeroOS",
    (await page.eval(`Boolean(document.querySelector('[role="dialog"][aria-labelledby="cases-title"] a[href="${companyPath}"]'))`)) === true);
  await ctx.screenshot(page, "cases-empty-1440");
  await page.press("Escape");

  await page.waitForHydrated("#ask-heroos");
  await page.type("#ask-heroos", NARRATIVE);
  // A double click on Send: the same button twice in one task.
  await page.eval(`(() => { const b = document.querySelector('button[aria-label="Send"]'); b.click(); b.click(); return true; })()`);
  await page.waitFor(`/^\\/workspaces\\/[^/]+\\/cases\\/[0-9a-f-]{36}$/.test(location.pathname)`, { message: "the new case opens" });
  await page.waitForText("Welcome to your Disciplinary case");
  const caseId = await page.eval("location.pathname.split('/').pop()");
  const instances = await owner(`SELECT count(*), min(c.case_type), min(i.created_by_user_id::text), min(c.title) FROM workflow_instances i JOIN cases c ON c.id = i.case_id WHERE i.company_id = ${quote(founder.companyId)}`);
  const TITLE = instances[0][3];
  const asked = await owner(`SELECT f.value #>> '{}', s.revision FROM case_facts f JOIN workflow_submissions s ON s.id = f.submission_id JOIN workflow_instances i ON i.id = f.instance_id
    WHERE i.case_id = ${quote(caseId)} AND f.fact_key = 'incident.narrative'`);
  check("CASE-3", "a double-clicked Send opens exactly one case, typed disciplinary by the server, neutrally titled, with the founder's words saved as written",
    UUID.test(caseId) && instances[0][0] === "1" && instances[0][1] === "disciplinary" && /^New case · /.test(TITLE ?? "") && !TITLE.includes("team member") &&
      JSON.stringify(asked) === JSON.stringify([[NARRATIVE, "1"]]),
    JSON.stringify({ instances, asked }));

  // The progress and "not available yet" lists are in the case status's folded "Full case details": open them as a person would.
  await openFullCaseDetails(page);
  const opened = await page.text();
  check("CASE-4", "the case says it is not AI, asks the initial questions, and pauses on the unconfirmed jurisdiction with stages coming later",
    opened.includes("not an AI assistant") && opened.includes("What happened?") && opened.includes("Paused: jurisdiction not confirmed") &&
      opened.includes("Needs information") && opened.includes("Coming later") && opened.includes("Expert review") && !/Hannah|AI demo/.test(opened),
    opened.slice(0, 200));
  await ctx.screenshot(page, "case-new-1440");
  await page.press("Escape");

  // The founder's words are already the first answer; the rest of the initial facts are still to give.
  await page.waitForHydrated("#q-incident-narrative");
  const prefilled = await page.eval(`document.getElementById("q-incident-narrative").value`);
  await page.type("#q-incident-date", incidentDay);
  await page.click("#q-incident-history-new");
  await page.click("#q-incident-discussed-with-employee-no");
  await page.clickText("button", "Save answers");
  await page.waitForText("Your answers are saved to this case.");
  const facts = await owner(`SELECT f.fact_key, f.value #>> '{}', s.revision, s.submitted_by_user_id IS NOT NULL
    FROM case_facts f JOIN workflow_submissions s ON s.id = f.submission_id JOIN workflow_instances i ON i.id = f.instance_id
    WHERE i.case_id = ${quote(caseId)} ORDER BY f.fact_key`);
  check("CASE-5", "the answers are stored in PostgreSQL as given, with revision and actor (the founder's words first, from Ask HeroOS)",
    prefilled === NARRATIVE &&
      JSON.stringify(facts) === JSON.stringify([
        ["incident.date", incidentDay, "2", "t"],
        ["incident.discussed_with_employee", "no", "2", "t"],
        ["incident.history", "new", "2", "t"],
        ["incident.narrative", NARRATIVE, "1", "t"],
      ]),
    JSON.stringify({ prefilled: prefilled === NARRATIVE, facts }));
  const saved = await page.text();
  check("CASE-6", "the saved answers appear as the employer's turn and progress follows them",
    saved.includes("You") && saved.includes("Awaiting jurisdiction confirmation") && saved.includes("4 of 5 answered"));

  await page.goto(`${webOrigin}${companyPath}/cases/${caseId}`);
  await page.waitForHydrated("#q-incident-narrative");
  const restored = await page.eval(`({ narrative: document.getElementById("q-incident-narrative").value, date: document.getElementById("q-incident-date").value,
    history: document.getElementById("q-incident-history-new").checked, discussed: document.getElementById("q-incident-discussed-with-employee-no").checked })`);
  check("CASE-7", "after a reload the answers are still there (read from PostgreSQL)",
    restored.narrative === NARRATIVE && restored.date === incidentDay && restored.history && restored.discussed, JSON.stringify(restored));

  await page.click("#q-incident-evidence-available-not_sure");
  await page.clickText("button", "Save answers");
  await page.waitForText("Your answers are saved to this case.");
  await openFullCaseDetails(page);
  const complete = await page.text();
  const completeView = await ctx.apiFetch(`/companies/${founder.companyId}/cases/${caseId}/workflow`, { token: founder.token });
  const unavailable = (completeView.json?.steps ?? []).filter((s) => !s.available).map((s) => s.key);
  check("CASE-8", "with every initial answer given but the company jurisdiction unconfirmed, the case is paused: jurisdiction-dependent steps are unavailable",
    complete.includes("Awaiting jurisdiction confirmation") && complete.includes("Blocked") &&
      completeView.json?.jurisdiction?.guidance_allowed === false &&
      JSON.stringify(unavailable) === JSON.stringify(["jurisdiction", "safety_screening"]) &&
      completeView.json?.intake?.hold?.reason === "company_jurisdiction_unconfirmed" &&
      // The harness installs (synthetic) progression rules, so the next stages are
      // the progression's pathway and stage items (without rules: "next_stages").
      completeView.json?.progress?.find((p) => p.key === "pathway")?.status === "blocked" &&
      completeView.json?.progress?.find((p) => p.key === "stage")?.status === "blocked",
    JSON.stringify(completeView.json?.status));

  await signOutFromMenu(page);
  await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/"`, { message: "signed out" });
  await ctx.signIn(page, founder.subject);
  // The old case-list address opens Ask HeroOS with the Cases drawer.
  await page.goto(`${webOrigin}${companyPath}/cases`);
  await page.waitForText(TITLE);
  await page.goto(`${webOrigin}${companyPath}/cases/${caseId}`);
  await openInitialFacts(page);
  const again = await page.eval(`document.getElementById("q-incident-narrative").value`);
  check("CASE-9", "after signing out and in again, the case and its answers are still there", again === NARRATIVE);

  await page.viewport(390, 844);
  await page.goto(`${webOrigin}${companyPath}/cases/${caseId}`);
  await openInitialFacts(page);
  const overflow = await page.overflow();
  check("CASE-10", "the guided workspace fits a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await ctx.screenshot(page, "case-saved-390");
  await page.viewport(1440, 900);
  await page.goto(`${webOrigin}${companyPath}/cases/${caseId}`);
  await openInitialFacts(page);
  await ctx.screenshot(page, "case-saved-1440");

  // ===== Duplicate creation through the BFF (concurrent, one key) =====
  const session = ctx.session(founder.token);
  const requestKey = crypto.randomUUID();
  const bffCreate = () =>
    ctx.webFetch(`/bff/companies/${founder.companyId}/workflows/disciplinary/cases`, {
      method: "POST",
      session,
      headers: { origin: webOrigin, "sec-fetch-site": "same-origin", "content-type": "application/json" },
      body: JSON.stringify({ title: "[SYNTHETIC E2E] Concurrent", requestKey }),
    });
  const concurrent = await Promise.all([bffCreate(), bffCreate(), bffCreate()]);
  const concurrentIds = new Set(concurrent.map((r) => r.json?.case?.id));
  const concurrentRows = await owner(`SELECT count(*) FROM workflow_instances WHERE request_key = ${quote(requestKey)}`);
  check("CASE-11", "three concurrent creations with one request key make one case", concurrent.every((r) => r.status === 200) && concurrentIds.size === 1 && concurrentRows[0][0] === "1",
    JSON.stringify(concurrent.map((r) => r.status)));

  // ===== Stale writes and replays =====
  const answersPath = `/companies/${founder.companyId}/cases/${caseId}/workflow/steps/initial_facts/answers`;
  const before = await owner(`SELECT count(*) FROM workflow_submissions s JOIN workflow_instances i ON i.id = s.instance_id WHERE i.case_id = ${quote(caseId)}`);
  const stale = await ctx.apiFetch(answersPath, { token: founder.token, method: "PUT", body: { expected_revision: 1, submission_key: crypto.randomUUID(), answers: { "incident.history": "not_sure" } } });
  const lastKey = (await owner(`SELECT s.idempotency_key FROM workflow_submissions s JOIN workflow_instances i ON i.id = s.instance_id WHERE i.case_id = ${quote(caseId)} ORDER BY s.revision DESC LIMIT 1`))[0][0];
  const replay = await ctx.apiFetch(answersPath, { token: founder.token, method: "PUT", body: { expected_revision: 2, submission_key: lastKey, answers: { "incident.evidence_available": "not_sure" } } });
  const after = await owner(`SELECT count(*) FROM workflow_submissions s JOIN workflow_instances i ON i.id = s.instance_id WHERE i.case_id = ${quote(caseId)}`);
  check("CASE-12", "a stale save is refused (409) and a replayed save is applied once (200, nothing new written)",
    stale.status === 409 && replay.status === 200 && replay.json?.workflow?.revision === 3 && before[0][0] === after[0][0], `${stale.status} ${replay.status} ${before} ${after}`);

  // ===== A member: no access at all (M2-01 interim policy: administrators only) =====
  const memberList = await ctx.apiFetch(casesApi(founder.companyId), { token: member.token });
  const memberView = await ctx.apiFetch(`/companies/${founder.companyId}/cases/${caseId}/workflow`, { token: member.token });
  const memberCreate = await ctx.apiFetch(casesApi(founder.companyId), { token: member.token, method: "POST", body: { title: "x", request_key: crypto.randomUUID() } });
  const memberSave = await ctx.apiFetch(answersPath, { token: member.token, method: "PUT", body: { expected_revision: 3, submission_key: crypto.randomUUID(), answers: { "incident.history": "not_sure" } } });
  const memberRecords = await ctx.apiFetch(`/companies/${founder.companyId}/cases`, { token: member.token });
  const memberRecord = await ctx.apiFetch(`/companies/${founder.companyId}/cases/${caseId}`, { token: member.token });
  const leaked = [memberList, memberView, memberCreate, memberSave, memberRecords, memberRecord].some((r) => r.text.includes(TITLE) || r.text.includes(NARRATIVE.slice(16, 50)));
  check("CASE-13", "a member cannot list, open, create or answer Disciplinary cases (403), and the case records hide them (list without it, record 404)",
    [memberList, memberView, memberCreate, memberSave].every((r) => r.status === 403) &&
      memberRecords.status === 200 && Array.isArray(memberRecords.json) && !memberRecords.json.some((c) => c.id === caseId) &&
      memberRecord.status === 404 && !leaked,
    `${memberList.status} ${memberView.status} ${memberCreate.status} ${memberSave.status} ${memberRecords.status} ${memberRecord.status} leaked=${leaked}`);
  const memberPage = await ctx.newPage();
  await memberPage.viewport(1440, 900);
  await ctx.signIn(memberPage, member.subject);
  await memberPage.goto(`${webOrigin}${companyPath}`);
  await memberPage.waitForText("What can HR do for you today?");
  const memberHome = await memberPage.eval(`({
    cases: Boolean(document.querySelector('button[aria-label="Cases"]')),
    box: { disabled: document.getElementById("ask-heroos")?.disabled, placeholder: document.getElementById("ask-heroos")?.placeholder },
  })`);
  await memberPage.goto(`${webOrigin}${companyPath}/cases`);
  await memberPage.waitForText("What can HR do for you today?");
  const memberListPage = await memberPage.text();
  await memberPage.goto(`${webOrigin}${companyPath}/cases/${caseId}`);
  await memberPage.waitForText("Cases are for company administrators");
  const memberCasePage = await memberPage.text();
  await ctx.screenshot(memberPage, "case-member-admin-only-1440");
  check("CASE-14", "in the browser a member can't open cases: a disabled box that says why, no Cases control, no case content",
    memberHome.cases === false && memberHome.box.disabled === true && memberHome.box.placeholder === "Only company administrators can open cases for now." &&
      ![memberListPage, memberCasePage].some((t) => t.includes(TITLE) || t.includes(NARRATIVE.slice(0, 40))),
    JSON.stringify(memberHome).slice(0, 200));
  await memberPage.close();

  // ===== Another Company =====
  const otherList = await ctx.apiFetch(casesApi(founder.companyId), { token: other.token });
  const otherView = await ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/workflow`, { token: other.token });
  const otherSave = await ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/workflow/steps/initial_facts/answers`, {
    token: other.token, method: "PUT", body: { expected_revision: 3, submission_key: crypto.randomUUID(), answers: { "incident.history": "not_sure" } },
  });
  const otherPage = await ctx.newPage();
  await ctx.signIn(otherPage, other.subject);
  await otherPage.goto(`${webOrigin}/workspaces/${other.companyId}/cases/${caseId}`);
  await otherPage.waitForText("This case can't be opened");
  check("CASE-15", "another Company's administrator gets 403 on the Company, 404 for the case (API and browser), and cannot write",
    otherList.status === 403 && otherView.status === 404 && otherSave.status === 404 && !(await otherPage.text()).includes(TITLE),
    `${otherList.status} ${otherView.status} ${otherSave.status}`);
  await otherPage.close();

  // ===== The database itself =====
  const asOther = await fixtures.runtimeQuery("SELECT count(*) FROM case_facts", { company: other.companyId });
  const asOwn = await fixtures.runtimeQuery("SELECT count(*) FROM case_facts", { company: founder.companyId });
  const tamper = await fixtures.runtimeQuery("UPDATE case_facts SET value = '\"x\"'", { company: founder.companyId });
  check("CASE-16", "as the API's own login, RLS hides the case facts from another Company, and facts cannot be rewritten",
    asOther.ok && asOther.rows[0][0] === "0" && asOwn.ok && Number(asOwn.rows[0][0]) >= 5 && !tamper.ok && /permission denied/.test(tamper.error),
    JSON.stringify({ asOther, asOwn, tamper }));

  await page.close();
  const logs = `${ctx.api.logs()}\n${ctx.web.logs()}`;
  check("CASE-17", "no case title or narrative appears in the API or web logs", !logs.includes(NARRATIVE.slice(16, 60)) && !logs.includes(TITLE));
}
