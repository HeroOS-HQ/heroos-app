// M2-02: the Disciplinary intake with the real components together.
// A UAE Federal Company (licensing answer + operator confirmation): the
// administrator answers the initial facts, confirms the case jurisdiction,
// gives the incident context (a follow-up appears, a caution is raised),
// clears the safety screening (intake recorded), then reports a high-risk
// factor (the case is held: no ticket, nothing promised), reloads, signs out
// and in, and corrects it (the hold is kept: changed answers never release an
// escalation). A DIFC Company gets no UAE Federal rule and is held for
// specialist review instead of screened. An API with the default setting never
// collects the sensitive screening. PostgreSQL rows, RLS and logs are checked
// too. Synthetic data only.
import { newFounder, quote } from "./common.mjs";

const TITLE = "[SYNTHETIC E2E] Intake journey";
const NARRATIVE = "[SYNTHETIC E2E] A team member posted rude remarks about a colleague after a shift ended.";
const AUTHORITY = "[SYNTHETIC E2E] Free Zone Authority";
const SCREENING = [
  "recent_complaint",
  "harassment_concern",
  "pregnancy_maternity",
  "sick_leave",
  "medical_condition",
  "whistleblower",
  "senior_employee",
  "criminal_allegation",
  "dismissal_without_notice",
].map((key) => `screening.${key}`);
const fieldId = (key) => `q-${key.replace(/[^a-z0-9]+/g, "-")}`;
const radio = (key, value) => `#${fieldId(key)}-${value}`;

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const owner = (sql) => fixtures.ownerQuery(sql);
  const confirm = (founder, args) => fixtures.operator(["confirm-jurisdiction", "--company", founder.companyId, ...args]);

  const fed = await newFounder(ctx, "intake-fed", {
    company_name: "[SYNTHETIC E2E] Intake Federal Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const difc = await newFounder(ctx, "intake-difc", {
    company_name: "[SYNTHETIC E2E] Intake DIFC Co.",
    blueprint: { licensing: { location: "difc" } },
  });
  const fedConfirmed = await confirm(fed, ["--jurisdiction", "uae_federal", "--licensing-location", "other", "--licensing-authority", AUTHORITY]);
  const difcConfirmed = await confirm(difc, ["--jurisdiction", "difc", "--licensing-location", "difc"]);
  const memberSubject = ctx.subject("intake-member");
  const provisioned = await fixtures.operator(["provision", "--company", fed.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  const member = { subject: memberSubject, token: ctx.token(memberSubject) };
  check("INTAKE-0", "fixtures: a UAE Federal and a DIFC Company confirmed by the operator, and a member of the first",
    fedConfirmed.code === 0 && difcConfirmed.code === 0 && provisioned.code === 0,
    JSON.stringify({ fedConfirmed, difcConfirmed, provisioned }).slice(0, 300));

  const casesApi = (founder) => `/companies/${founder.companyId}/workflows/disciplinary/cases`;
  const created = await ctx.apiFetch(casesApi(fed), { token: fed.token, method: "POST", body: { title: TITLE, request_key: crypto.randomUUID() } });
  const caseId = created.json?.id;
  const casePath = `/workspaces/${fed.companyId}/cases/${caseId}`;
  const caseSql = quote(caseId);
  const evaluations = () =>
    owner(`SELECT e.status, coalesce(e.hold, '-'), coalesce(e.hold_reason, '-'), coalesce(e.jurisdiction, '-'), e.screening, e.definition_version
      FROM workflow_evaluations e JOIN workflow_submissions s ON s.id = e.submission_id JOIN workflow_instances i ON i.id = e.instance_id
      WHERE i.case_id = ${caseSql} ORDER BY s.revision`);
  const incidentDay = new Date(Date.now() - 5 * 86_400_000).toISOString().slice(0, 10);

  // ===== Browser: the UAE Federal intake (1440 wide) =====
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#q-incident-narrative");
  const opened = await page.text();
  check("INTAKE-1", "a new case in a UAE Federal Company asks the initial facts and offers four question groups; the screening waits for the case jurisdiction",
    created.status === 201 && opened.includes("1. Initial facts") && opened.includes("2. Employment jurisdiction") &&
      opened.includes("3. Incident context") && opened.includes("4. Safety screening") && opened.includes("Confirm the jurisdiction for this case"),
    opened.slice(0, 300));

  await page.type("#q-incident-narrative", NARRATIVE);
  await page.type("#q-incident-date", incidentDay);
  await page.click(radio("incident.history", "new"));
  await page.click(radio("incident.discussed_with_employee", "no"));
  await page.click(radio("incident.evidence_available", "yes"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Continue to Employment jurisdiction");
  await page.clickText("button", "Continue to Employment jurisdiction");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("jurisdiction.case_confirmation", "uae_federal"))}))`, { message: "jurisdiction group" });
  const options = await page.eval(`[...document.querySelectorAll('input[name="${fieldId("jurisdiction.case_confirmation")}"]')].map((i) => i.closest("label").innerText.trim())`);
  await page.click(radio("jurisdiction.case_confirmation", "uae_federal"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Jurisdiction confirmed for this case");
  const afterJurisdiction = await page.text();
  check("INTAKE-2", "the case jurisdiction is confirmed against the company's operator confirmation, never chosen freely",
    JSON.stringify(options) === JSON.stringify(["Yes, UAE Federal (MOHRE)", "No, a different jurisdiction applies", "Not sure"]) &&
      afterJurisdiction.includes("Based on your company's confirmed jurisdiction and your confirmation for this case."),
    JSON.stringify(options));

  await page.clickText("button", "Continue to Incident context");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("context.location", "outside_work"))}))`, { message: "context group" });
  const beforeFollowUp = await page.eval(`Boolean(document.getElementById(${JSON.stringify(fieldId("context.work_connection") + "-yes")}))`);
  await page.click(radio("context.location", "outside_work"));
  await page.waitFor(`Boolean(document.getElementById(${JSON.stringify(fieldId("context.work_connection") + "-not_sure")}))`, { message: "follow-up appears" });
  await page.click(radio("context.work_connection", "not_sure"));
  await page.click(radio("history.same_incident_sanction", "no"));
  await page.click(radio("context.policy_awareness", "yes"));
  await page.click(radio("evidence.witnesses", "yes"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Caution: Conduct outside work");
  check("INTAKE-3", "a follow-up appears only after the answer that needs it, and off-duty conduct without a stated work connection is cautioned",
    beforeFollowUp === false && (await page.text()).includes("Caution: Conduct outside work"));

  await page.clickText("button", "Continue to Safety screening");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio(SCREENING[0], "no"))}))`, { message: "screening group" });
  const screeningPage = await page.text();
  const provisional = screeningPage.includes("haven't been legally reviewed yet") && screeningPage.includes("Demo environment: made-up examples only");
  for (const key of SCREENING) await page.click(radio(key, "no"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Intake recorded");
  const recorded = await page.text();
  check("INTAKE-4", "the screening is marked provisional and demo-only; with every answer No, the intake is recorded as a preliminary status, not a legal assessment",
    provisional && recorded.includes("Safety screening completed") && recorded.includes("not a legal assessment"),
    recorded.slice(0, 200));
  await ctx.screenshot(page, "intake-recorded-1440");

  await page.click(radio("screening.sick_leave", "yes"));
  await page.clickText("button", "Save answers");
  await page.waitForText("On hold: specialist review needed");
  const held = await page.text();
  const tickets = await owner(`SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE '%ticket%' OR tablename LIKE '%escalat%')`);
  const view = await ctx.apiFetch(`/companies/${fed.companyId}/cases/${caseId}/workflow`, { token: fed.token });
  check("INTAKE-5", "a high-risk answer holds the case for specialist review: the factor is named, nothing is promised, no ticket exists",
    held.includes("Sick leave") && held.includes("hasn't contacted anyone") && held.includes("isn't a finding about the employee") &&
      !/will contact|ticket raised|we'll be in touch/i.test(held) && tickets[0][0] === "0" &&
      view.json?.intake?.hold?.reason === "high_risk_factors" && view.json?.intake?.next_stage_open === false,
    JSON.stringify(view.json?.intake?.hold?.reason));
  await ctx.screenshot(page, "intake-held-1440");

  const stored = await evaluations();
  check("INTAKE-6", "PostgreSQL holds one evaluation per save, the last recording the hold and why",
    stored.length === 5 &&
      JSON.stringify(stored.at(-1)) === JSON.stringify(["held_for_specialist_review", "specialist_review", "high_risk_factors", "uae_federal", "positive", "2"]) &&
      stored[3][0] === "intake_recorded",
    JSON.stringify(stored));

  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("On hold: specialist review needed");
  await page.clickText("button", "Sign out");
  await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/"`, { message: "signed out" });
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("On hold: specialist review needed");
  const history = await page.eval(`document.querySelector('section[aria-labelledby="history-heading"]').innerText`);
  check("INTAKE-7", "after a reload and a new sign-in the hold, the answers and the case history are all still there",
    history.includes("Case held for specialist review") && history.includes("Jurisdiction confirmed for this case: UAE Federal (MOHRE)") &&
      history.includes("Caution raised: Conduct outside work") && history.includes("Intake recorded"),
    history.slice(0, 400));

  await page.viewport(390, 844);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("On hold: specialist review needed");
  const overflow = await page.overflow();
  check("INTAKE-8", "the held case fits a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await ctx.screenshot(page, "intake-held-390");
  await page.viewport(1440, 900);

  // Correcting the answer is saved, but it doesn't release the hold.
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#q-incident-narrative");
  await page.clickText("button", "4. Safety screening");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("screening.sick_leave", "no"))}))`, { message: "screening group" });
  await page.click(radio("screening.sick_leave", "no"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Hold kept after answers changed");
  const kept = await page.text();
  check("INTAKE-9", "a corrected answer is saved but never releases the hold: the case stays held and the history says so",
    kept.includes("On hold: specialist review needed") && kept.includes("don't release the hold") &&
      kept.includes("Current screening") && !kept.includes("Hold lifted"),
    kept.slice(0, 200));
  await ctx.screenshot(page, "intake-history-1440");

  // ===== API: uncertainty, replays, members, other Companies =====
  const revision = () => ctx.apiFetch(`/companies/${fed.companyId}/cases/${caseId}/workflow`, { token: fed.token }).then((r) => r.json?.workflow?.revision);
  const screeningPath = `/companies/${fed.companyId}/cases/${caseId}/workflow/steps/safety_screening/answers`;
  const key = crypto.randomUUID();
  const uncertain = await ctx.apiFetch(screeningPath, {
    token: fed.token, method: "PUT", body: { expected_revision: await revision(), submission_key: key, answers: { "screening.senior_employee": "not_sure" } },
  });
  const replayed = await ctx.apiFetch(screeningPath, {
    token: fed.token, method: "PUT", body: { expected_revision: uncertain.json?.workflow?.revision - 1, submission_key: key, answers: { "screening.senior_employee": "not_sure" } },
  });
  const afterReplay = await evaluations();
  check("INTAKE-10", "a Not sure screening answer never clears the screening (the case stays held), and a replayed save adds no second evaluation",
    uncertain.json?.intake?.screening === "not_cleared" && uncertain.json?.status?.code === "held_for_specialist_review" &&
      uncertain.json?.intake?.hold?.reason === "earlier_escalation" && uncertain.json?.intake?.next_stage_open === false &&
      replayed.status === 200 && afterReplay.length === 7,
    `${uncertain.status} ${uncertain.json?.intake?.screening} ${uncertain.json?.status?.code} ${replayed.status} ${afterReplay.length}`);

  const memberSave = await ctx.apiFetch(screeningPath, { token: member.token, method: "PUT", body: { expected_revision: 0, submission_key: crypto.randomUUID(), answers: { "screening.sick_leave": "no" } } });
  const otherView = await ctx.apiFetch(`/companies/${difc.companyId}/cases/${caseId}/workflow`, { token: difc.token });
  const otherSave = await ctx.apiFetch(`/companies/${difc.companyId}/cases/${caseId}/workflow/steps/safety_screening/answers`, {
    token: difc.token, method: "PUT", body: { expected_revision: 0, submission_key: crypto.randomUUID(), answers: { "screening.sick_leave": "no" } },
  });
  check("INTAKE-11", "a member cannot answer the screening (403) and another Company's administrator cannot see or write the case (404)",
    memberSave.status === 403 && otherView.status === 404 && otherSave.status === 404, `${memberSave.status} ${otherView.status} ${otherSave.status}`);

  // ===== DIFC: no UAE Federal rule; held for specialist review =====
  const difcCase = (await ctx.apiFetch(casesApi(difc), { token: difc.token, method: "POST", body: { title: "[SYNTHETIC E2E] DIFC intake", request_key: crypto.randomUUID() } })).json?.id;
  const difcSave = (step, answers, rev) =>
    ctx.apiFetch(`/companies/${difc.companyId}/cases/${difcCase}/workflow/steps/${step}/answers`, {
      token: difc.token, method: "PUT", body: { expected_revision: rev, submission_key: crypto.randomUUID(), answers },
    });
  await difcSave("initial_facts", { "incident.narrative": "[SYNTHETIC E2E] DIFC incident.", "incident.history": "new" }, 0);
  await difcSave("jurisdiction", { "jurisdiction.case_confirmation": "difc" }, 1);
  const difcContext = await difcSave("incident_context", {
    "context.location": "outside_work", "context.work_connection": "no", "context.policy_awareness": "no", "history.same_incident_sanction": "yes", "evidence.witnesses": "no",
  }, 2);
  const difcScreening = await difcSave("safety_screening", { "screening.sick_leave": "no" }, 3);
  const said = (difcContext.json?.conversation ?? []).filter((m) => m.kind !== "answer_confirmation").map((m) => `${m.title} ${m.body}`).join(" ");
  check("INTAKE-12", "a DIFC case gets no UAE Federal caution or screening and is held because no approved screening covers it",
    difcContext.json?.intake?.case_jurisdiction?.jurisdiction === "difc" && difcContext.json?.intake?.hold?.reason === "screening_not_covered" &&
      difcContext.json?.intake?.cautions?.length === 0 && difcScreening.status === 409 && !/UAE Federal|MOHRE|Article/.test(said),
    `${difcContext.json?.intake?.hold?.reason} ${difcScreening.status}`);
  const difcPage = await ctx.newPage();
  await difcPage.viewport(1440, 900);
  await ctx.signIn(difcPage, difc.subject);
  await difcPage.goto(`${webOrigin}/workspaces/${difc.companyId}/cases/${difcCase}`);
  const difcLoaded = await difcPage.waitForText("On hold: specialist review needed").then(() => true, () => false);
  const difcText = await difcPage.text();
  const difcUrl = await difcPage.eval("location.pathname");
  check("INTAKE-13", "in the browser the DIFC case explains the hold without UAE Federal guidance",
    difcLoaded && difcText.includes("isn't available for DIFC cases yet") && !difcText.includes("Caution:"), `${difcUrl} ${difcText.slice(0, 300)}`);
  await ctx.screenshot(difcPage, "intake-difc-held-1440");
  await difcPage.close();

  // ===== An API with the default setting never collects the screening =====
  const defaultApi = ctx.makeApi({ databaseUrl: ctx.urls.runtime(process.env.E2E_DATABASE), label: "api-screening-default" });
  await defaultApi.start({ extraEnv: { HEROOS_SENSITIVE_SCREENING: "disabled" } });
  const viaDefault = (path, init = {}) =>
    fetch(`${defaultApi.url}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${fed.token}`, "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  const defaultView = await (await viaDefault(`/companies/${fed.companyId}/cases/${caseId}/workflow`)).json();
  const defaultSave = await viaDefault(screeningPath, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: defaultView.workflow?.revision, submission_key: crypto.randomUUID(), answers: { "screening.sick_leave": "no" } }),
  });
  await defaultApi.stop();
  const screeningStep = (defaultView.steps ?? []).find((s) => s.key === "safety_screening");
  check("INTAKE-16", "with the default setting the API refuses the sensitive screening (409), says so, and still keeps the earlier hold",
    defaultView.sensitive_screening === "disabled" && screeningStep?.available === false &&
      screeningStep?.unavailable_reason === "The safety screening isn't enabled in this environment." &&
      defaultSave.status === 409 && defaultView.status?.code === "held_for_specialist_review",
    `${defaultView.sensitive_screening} ${screeningStep?.available} ${defaultSave.status} ${defaultView.status?.code}`);

  // ===== The database itself =====
  const asOther = await fixtures.runtimeQuery(`SELECT count(*) FROM workflow_evaluations e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${caseSql}`, { company: difc.companyId });
  const asOwn = await fixtures.runtimeQuery(`SELECT count(*) FROM workflow_evaluations e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${caseSql}`, { company: fed.companyId });
  const tamper = await fixtures.runtimeQuery("UPDATE workflow_evaluations SET hold = NULL, hold_reason = NULL", { company: fed.companyId });
  const remove = await fixtures.runtimeQuery("DELETE FROM workflow_evaluations", { company: fed.companyId });
  check("INTAKE-14", "as the API's own login, RLS hides the evaluations from another Company, and they can be neither rewritten nor deleted",
    asOther.ok && asOther.rows[0][0] === "0" && asOwn.ok && asOwn.rows[0][0] === "7" && !tamper.ok && !remove.ok &&
      /permission denied/.test(tamper.error) && /permission denied/.test(remove.error),
    JSON.stringify({ asOther, asOwn, tamper, remove }));

  await page.close();
  const logs = `${ctx.api.logs()}\n${ctx.web.logs()}`;
  check("INTAKE-15", "no title, narrative or screening answer appears in the API or web logs; holds are logged by kind only",
    !logs.includes(NARRATIVE.slice(16, 60)) && !logs.includes("Intake journey") && !/sick_leave|high_risk/.test(logs) &&
      logs.includes("Workflow case held"));
}
