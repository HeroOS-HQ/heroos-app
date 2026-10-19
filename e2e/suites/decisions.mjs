// M2-04: employer decision records and the unified case history with the real
// components together (synthetic rules installed as a deployment does). A UAE
// Federal Company's administrator, on a Case with a stage in progress, sees
// what a record is and isn't, is stopped by the form's checks, records a
// factual decision (a named decision-maker, a date, an explanation, an
// evidence reference), finds it at once in the unified history, corrects it
// (the original stays, marked replaced), reloads and signs in again (all of it
// persists) and fits a phone. Through the API and the BFF: retries, stale and
// concurrent corrections, members and other Companies, cross-case
// corrections, forged actors and unsafe categories, a record that can't move a
// stage or release a hold, an API without rules, and paging. The database, the
// logs and the schema are checked too. Synthetic data only.
import { newFounder, quote } from "./common.mjs";

const TITLE = "[SYNTHETIC E2E] Decisions journey";
const NARRATIVE = "[SYNTHETIC E2E] A team member repeatedly missed the shift handover checklist.";
const AUTHORITY = "[SYNTHETIC E2E] Free Zone Authority";
const SUMMARY = "[SYNTHETIC E2E] Supervisor held a check-in meeting";
const EXPLANATION = "[SYNTHETIC E2E] The supervisor met the team member about the handovers.\nNotes were taken.";
const ROLE = "[SYNTHETIC E2E] Shift supervisor";
const EVIDENCE = "[SYNTHETIC E2E] Check-in meeting notes";
const REASON = "[SYNTHETIC E2E] The meeting date was wrong.";
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
// The screening questions' labels: never repeated in any history.
const SCREENING_LABELS = ["Pregnancy or maternity", "Sick leave", "Medical condition", "Whistleblowing", "Recent complaint"];

const select = (page, selector, value) =>
  page.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) throw new Error("no element " + ${JSON.stringify(selector)});
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const owner = (sql) => fixtures.ownerQuery(sql);
  const confirm = (founder, args) => fixtures.operator(["confirm-jurisdiction", "--company", founder.companyId, ...args]);

  const fed = await newFounder(ctx, "decisions-fed", {
    company_name: "[SYNTHETIC E2E] Decisions Federal Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const other = await newFounder(ctx, "decisions-other", {
    company_name: "[SYNTHETIC E2E] Decisions Other Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const confirmed = await confirm(fed, ["--jurisdiction", "uae_federal", "--licensing-location", "other", "--licensing-authority", AUTHORITY]);
  const memberSubject = ctx.subject("decisions-member");
  const provisioned = await fixtures.operator(["provision", "--company", fed.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  const member = { token: ctx.token(memberSubject) };

  const casesApi = `/companies/${fed.companyId}/workflows/disciplinary/cases`;
  const caseApi = (id, path = "") => `/companies/${fed.companyId}/cases/${id}${path}`;
  const newCase = async (title, screening = "no") => {
    const id = (await ctx.apiFetch(casesApi, { token: fed.token, method: "POST", body: { title, request_key: crypto.randomUUID() } })).json?.id;
    const save = (step, answers, revision) =>
      ctx.apiFetch(caseApi(id, `/workflow/steps/${step}/answers`), {
        token: fed.token, method: "PUT", body: { expected_revision: revision, submission_key: crypto.randomUUID(), answers },
      });
    await save("initial_facts", {
      "incident.narrative": NARRATIVE, "incident.date": "2026-10-10", "incident.history": "new",
      "incident.discussed_with_employee": "yes", "incident.evidence_available": "yes",
    }, 0);
    await save("jurisdiction", { "jurisdiction.case_confirmation": "uae_federal" }, 1);
    await save("incident_context", {
      "context.location": "at_work", "history.same_incident_sanction": "no", "context.policy_awareness": "yes", "evidence.witnesses": "yes",
    }, 2);
    const last = await save("safety_screening", Object.fromEntries(SCREENING.map((key) => [key, screening])), 3);
    return { id, view: last.json };
  };
  const view = (id, token = fed.token) => ctx.apiFetch(caseApi(id, "/workflow"), { token });
  const pathway = (id, revision, choice = "less_serious") =>
    ctx.apiFetch(caseApi(id, "/workflow/progression/pathway"), {
      token: fed.token, method: "POST", body: { expected_revision: revision, request_key: crypto.randomUUID(), pathway: choice },
    });
  const move = (id, revision, transition) =>
    ctx.apiFetch(caseApi(id, "/workflow/progression/transitions"), {
      token: fed.token, method: "POST", body: { expected_revision: revision, request_key: crypto.randomUUID(), transition },
    });
  const recordBody = (revision, overrides = {}) => ({
    expected_revision: revision,
    request_key: crypto.randomUUID(),
    category: "employer_observation",
    summary: "[SYNTHETIC E2E] An observation",
    explanation: "[SYNTHETIC E2E] Observed and noted.",
    occurred_on: "2026-10-12",
    decision_maker: "recorder",
    evidence_status: "none",
    ...overrides,
  });
  const record = (id, body, token = fed.token, company = fed.companyId) =>
    ctx.apiFetch(`/companies/${company}/cases/${id}/decisions`, { token, method: "POST", body });
  const correct = (id, recordId, body, token = fed.token, company = fed.companyId) =>
    ctx.apiFetch(`/companies/${company}/cases/${id}/decisions/${recordId}/corrections`, {
      token, method: "POST", body: { relation: "correction", change_reason: "[SYNTHETIC E2E] Correction.", ...body },
    });

  // A Case with the intake recorded, a pathway and a stage in progress.
  const recorded = await newCase(TITLE);
  const caseId = recorded.id;
  const chosen = await pathway(caseId, recorded.view?.workflow?.revision);
  const started = await move(caseId, chosen.json?.workflow?.revision, "start:test_check_in");
  check("DEC-0", "fixtures: a confirmed UAE Federal Company, a Case with a stage in progress, a member and another Company",
    confirmed.code === 0 && provisioned.code === 0 && started.json?.progression?.status?.code === "in_stage" &&
      started.json?.decisions?.records?.length === 0 && started.json?.timeline?.entries?.length > 0,
    JSON.stringify(started.json?.progression?.status));

  const records = () =>
    owner(`SELECT d.id, d.relation, d.supersedes_id, d.summary, d.occurred_on, d.recorded_by_user_id, d.revision
      FROM workflow_decision_records d JOIN workflow_instances i ON i.id = d.instance_id
      WHERE i.case_id = ${quote(caseId)} ORDER BY d.revision`);
  const progressCount = async (id = caseId) =>
    Number(await fixtures.ownerValue(`SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${quote(id)}`));
  const founderUser = await fixtures.ownerValue(`SELECT user_id FROM user_identities WHERE subject = ${quote(fed.subject)} AND issuer = ${quote(ctx.issuer.issuer)}`);
  const casePath = `/workspaces/${fed.companyId}/cases/${caseId}`;
  const section = (page) => page.eval(`document.getElementById("decisions-history").innerText`);
  const historyText = (page) => page.eval(`document.querySelector('section[aria-labelledby="history-heading"]').innerText`);

  // ===== Browser (1440 wide) =====
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#decisions-history button");
  const opened = await section(page);
  const openedHistory = await historyText(page);
  check("DEC-1", "the case shows Decisions & history: what a record is and isn't, the limits, no records, and the unified history of every earlier step",
    opened.includes("What a record is, and isn't") && opened.includes("isn't a warning, a penalty") &&
      opened.includes("can't be recorded here") && opened.includes("Records don't start or complete stages") &&
      opened.includes("No records yet.") && openedHistory.includes("Stage started: Test stage 1") &&
      openedHistory.includes("Pathway recorded: Less serious (your decision)") && openedHistory.includes("Intake recorded") &&
      openedHistory.includes("Case created") && /WORKFLOW STEP|Workflow step/.test(openedHistory),
    opened.slice(0, 300));
  await ctx.screenshotOf(page, "decisions-start-1440", "#decisions-history");

  await page.clickText("#decisions-history button", "Add a record");
  await page.waitForText("What are you recording?");
  await page.clickText("#decisions-history button", "Save record");
  await page.waitForText("Some details need attention");
  const refusedForm = await section(page);
  check("DEC-2", "an incomplete form is stopped in the browser: what's missing is listed and nothing is sent",
    refusedForm.includes("Choose what you're recording.") && refusedForm.includes("Say who is responsible.") &&
      refusedForm.includes("Say whether supporting evidence exists.") && (await records()).length === 0,
    refusedForm.slice(0, 300));

  await page.click("#decision-category-meeting_recorded");
  await page.type("#decision-summary", SUMMARY);
  await page.type("#decision-date", "2026-10-12");
  await page.click("#decision-maker-other");
  await page.waitFor(`Boolean(document.getElementById("decision-maker-role"))`, { message: "role field" });
  await page.type("#decision-maker-role", ROLE);
  await page.type("#decision-explanation", EXPLANATION);
  await page.click("#decision-evidence-held");
  await page.waitFor(`Boolean(document.getElementById("decision-evidence-0-kind"))`, { message: "evidence fields" });
  await select(page, "#decision-evidence-0-kind", "meeting_note");
  await page.type("#decision-evidence-0-description", EVIDENCE);
  await page.type("#decision-evidence-0-reference", "HR-E2E-014");
  await ctx.screenshotOf(page, "decisions-form-1440", "#decisions-history");
  await page.clickText("#decisions-history button", "Save record");
  await page.waitForText("Record saved");
  const saved = await section(page);
  const stored = await records();
  const afterRecord = await view(caseId);
  check("DEC-3", "the record is saved once, as the signed-in administrator, appears at once in the history, and the workflow didn't change",
    stored.length === 1 && stored[0][1] === "original" && stored[0][3] === SUMMARY && stored[0][5] === founderUser &&
      saved.includes("The workflow hasn't changed") && saved.includes(`${ROLE} (as stated by your company)`) &&
      saved.includes("HR-E2E-014") && (await historyText(page)).includes("Employer record: Meeting or discussion recorded") &&
      afterRecord.json?.progression?.status?.code === "in_stage" && (await progressCount()) === 2,
    JSON.stringify(stored));
  await ctx.screenshotOf(page, "decisions-recorded-1440", "#decisions-history");

  await page.clickText("#decisions-history button", "Correct");
  await page.waitForText("Why are you correcting it?");
  await page.type("#decision-date", "2026-10-13");
  await page.type("#decision-change-reason", REASON);
  await page.clickText("#decisions-history button", "Save correction");
  await page.waitForText("Correction saved");
  const correctedText = await section(page);
  const chain = await records();
  check("DEC-4", "a correction is a new current version; the original stays unchanged in the history, marked replaced",
    chain.length === 2 && chain[1][1] === "correction" && chain[1][2] === chain[0][0] && chain[0][4] === "2026-10-12" &&
      chain[1][4] === "2026-10-13" && correctedText.includes("Corrected · version 2") &&
      correctedText.includes("Earlier versions (1), kept in the history") &&
      (await historyText(page)).includes("Employer record corrected: Meeting or discussion recorded"),
    JSON.stringify(chain));
  await ctx.screenshotOf(page, "decisions-corrected-1440", "#decisions-history");

  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Decisions & history");
  await page.clickText("button", "Sign out");
  await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/"`, { message: "signed out" });
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitFor(`Boolean(document.querySelector('section[aria-labelledby="history-heading"]'))`, { message: "case history" });
  const persisted = await section(page);
  const persistedHistory = await historyText(page);
  check("DEC-5", "after a reload and a new sign-in, both versions and the unified history are all still there",
    persisted.includes(SUMMARY) && persisted.includes("Corrected · version 2") &&
      persistedHistory.includes("Employer record corrected: Meeting or discussion recorded") &&
      persistedHistory.includes("Employer record: Meeting or discussion recorded") && /Replaced|REPLACED/.test(persistedHistory) &&
      persistedHistory.includes("Stage started: Test stage 1"),
    persistedHistory.slice(0, 300));

  await page.viewport(390, 844);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Decisions & history");
  const overflow = await page.overflow();
  check("DEC-6", "Decisions & history fits a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await ctx.screenshotOf(page, "decisions-390", "#decisions-history");
  await page.viewport(1440, 900);

  // ===== API: retries, stale and concurrent requests =====
  let revision = (await view(caseId)).json?.workflow?.revision;
  const body = recordBody(revision);
  const first = await record(caseId, body);
  const again = await record(caseId, body);
  const stale = await record(caseId, recordBody(revision));
  check("DEC-7", "a retried record is saved once with the same answer; a stale revision is a conflict",
    first.status === 200 && again.status === 200 && again.json?.decisions?.saved === first.json?.decisions?.saved &&
      (await records()).length === 3 && stale.status === 409,
    `${first.status} ${again.status} ${stale.status}`);
  revision = first.json?.workflow?.revision;
  const target = first.json?.decisions?.saved;
  const raced = await Promise.all([0, 1, 2].map((i) => correct(caseId, target, recordBody(revision, { summary: `[SYNTHETIC E2E] Version ${i}` }))));
  const winner = raced.find((r) => r.status === 200);
  check("DEC-8", "corrections of one record racing are serialized: exactly one is saved, the others are conflicts",
    JSON.stringify(raced.map((r) => r.status).sort()) === JSON.stringify([200, 409, 409]) && (await records()).length === 4,
    JSON.stringify(raced.map((r) => r.status)));
  revision = winner?.json?.workflow?.revision;

  // ===== Access =====
  const latest = winner?.json?.decisions?.saved;
  const held = await newCase("[SYNTHETIC E2E] Decisions held", "no");
  const heldSave = await ctx.apiFetch(caseApi(held.id, "/workflow/steps/safety_screening/answers"), {
    token: fed.token, method: "PUT",
    body: { expected_revision: held.view?.workflow?.revision, submission_key: crypto.randomUUID(), answers: { "screening.whistleblower": "yes", "screening.sick_leave": "yes" } },
  });
  const memberCalls = await Promise.all([
    ctx.apiFetch(caseApi(caseId, "/decisions"), { token: member.token }),
    ctx.apiFetch(caseApi(caseId, "/history"), { token: member.token }),
    ctx.apiFetch(`/companies/${fed.companyId}/workflows/disciplinary/decision-categories`, { token: member.token }),
    record(caseId, recordBody(revision), member.token),
  ]);
  const otherCalls = await Promise.all([
    ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/decisions`, { token: other.token }),
    ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/history`, { token: other.token }),
    correct(caseId, latest, recordBody(revision), other.token, other.companyId),
  ]);
  const crossCase = await correct(held.id, latest, recordBody(heldSave.json?.workflow?.revision));
  check("DEC-9", "a member can't read or record (403); another Company can't find the case or its records (404); a record can't be corrected from another case (404)",
    memberCalls.every((r) => r.status === 403) && otherCalls.every((r) => r.status === 404) && crossCase.status === 404 &&
      (await records()).length === 4,
    `${memberCalls.map((r) => r.status)} ${otherCalls.map((r) => r.status)} ${crossCase.status}`);

  const forged = await Promise.all([
    record(caseId, { ...recordBody(revision), recorded_by_user_id: founderUser }),
    record(caseId, { ...recordBody(revision), legal_approval: true }),
    record(caseId, recordBody(revision, { category: "formal_warning_issued" })),
    record(caseId, recordBody(revision, { evidence_status: "held", evidence: [{ kind: "policy", description: "https://files.example.invalid/x" }] })),
    // HeroOS can't be named as the decision-maker or as the source of evidence.
    record(caseId, recordBody(revision, { decision_maker: "other", decision_maker_role: "HeroOS specialist" })),
    record(caseId, recordBody(revision, { evidence_status: "held", evidence: [{ kind: "internal_document", description: "HeroOS verified document" }] })),
  ]);
  check("DEC-10", "a forged actor, an approval flag, an unsafe category, a link as evidence or HeroOS named as decision-maker or evidence source is refused (422) and never echoed",
    forged.every((r) => r.status === 422) && forged.every((r) => !r.text.includes("files.example.invalid") && !r.text.includes(founderUser) && !r.text.includes("HeroOS specialist")) &&
      (await records()).length === 4,
    forged.map((r) => r.status).join(","));

  // ===== A record never authorizes anything =====
  const beforeProgress = await progressCount();
  const claim = await record(caseId, recordBody(revision, { category: "other_note", summary: "[SYNTHETIC E2E] Stage complete; formal warning issued" }));
  const completion = await move(caseId, claim.json?.workflow?.revision, "complete:test_check_in");
  const heldBefore = heldSave.json?.status?.code;
  const heldNote = await record(held.id, recordBody(heldSave.json?.workflow?.revision, {
    category: "internal_pause_or_follow_up", summary: "[SYNTHETIC E2E] Specialist review done, hold cleared",
  }));
  const heldChoice = await pathway(held.id, heldNote.json?.workflow?.revision);
  check("DEC-11", "a record can't complete a stage or release a hold: the stage stays in progress, completion is refused, the held case stays held",
    claim.status === 200 && claim.json?.progression?.status?.code === "in_stage" &&
      completion.json?.progression?.attempt?.outcome === "rejected" && (await progressCount()) === beforeProgress + 1 &&
      heldBefore === "held_for_specialist_review" && heldNote.json?.status?.code === "held_for_specialist_review" &&
      heldNote.json?.progression?.gate?.code === "case_held" && heldChoice.json?.progression?.attempt?.decision === "escalate" &&
      heldChoice.json?.progression?.pathway === null,
    `${completion.json?.progression?.attempt?.outcome} ${heldNote.json?.status?.code} ${heldChoice.json?.progression?.attempt?.decision}`);

  const noRules = ctx.makeApi({ databaseUrl: ctx.urls.runtime(process.env.E2E_DATABASE), label: "api-no-rules-decisions" });
  await noRules.start({ rules: false });
  const viaNoRules = async (path, init = {}) => {
    const response = await fetch(`${noRules.url}${path}`, { ...init, headers: { Authorization: `Bearer ${fed.token}`, "Content-Type": "application/json" } });
    return { status: response.status, json: await response.json().catch(() => null) };
  };
  const noRulesView = await viaNoRules(caseApi(caseId, "/workflow"));
  const noRulesRecord = await viaNoRules(caseApi(caseId, "/decisions"), { method: "POST", body: JSON.stringify(recordBody(noRulesView.json?.workflow?.revision)) });
  await noRules.stop();
  check("DEC-12", "without installed rules, progression is unavailable but factual records can still be saved",
    noRulesView.json?.progression?.status?.code === "unavailable" && noRulesRecord.status === 200 &&
      noRulesRecord.json?.decisions?.records?.[0]?.context?.progression_status === "unavailable",
    `${noRulesView.json?.progression?.status?.code} ${noRulesRecord.status}`);

  // ===== The unified history: order, paging, the BFF read, nothing sensitive =====
  const full = await ctx.apiFetch(caseApi(caseId, "/history?limit=100"), { token: fed.token });
  const pages = [];
  let cursor = null;
  for (;;) {
    const page = await ctx.apiFetch(caseApi(caseId, `/history?limit=4${cursor ? `&before=${encodeURIComponent(cursor)}` : ""}`), { token: fed.token });
    pages.push(...(page.json?.entries ?? []).map((e) => e.id));
    cursor = page.json?.next_before;
    if (!cursor) break;
  }
  const again2 = await ctx.apiFetch(caseApi(caseId, "/history?limit=100"), { token: fed.token });
  const ids = full.json?.entries?.map((e) => e.id) ?? [];
  const session = ctx.session(fed.token);
  const bff = await ctx.webFetch(`/bff/companies/${fed.companyId}/cases/${caseId}/history?before=${encodeURIComponent(ids[3])}`, {
    session, headers: { "Sec-Fetch-Site": "same-origin" },
  });
  const crossSite = await ctx.webFetch(`/bff/companies/${fed.companyId}/cases/${caseId}/history`, {
    session, headers: { "Sec-Fetch-Site": "cross-site" },
  });
  check("DEC-13", "the history is newest first, the same every time, and its pages cover it exactly once; the BFF reads a page for a same-origin session only",
    full.status === 200 && ids.length === full.json?.total && JSON.stringify(pages) === JSON.stringify(ids) &&
      JSON.stringify(again2.json?.entries) === JSON.stringify(full.json?.entries) && ids.at(-1) === "created" &&
      bff.status === 200 && bff.json?.page?.entries?.[0]?.id === ids[4] && crossSite.status === 403,
    `${ids.length} ${pages.length} ${bff.status} ${crossSite.status}`);

  const heldHistory = await ctx.apiFetch(caseApi(held.id, "/history?limit=100"), { token: fed.token });
  const heldText = (heldHistory.json?.entries ?? []).map((e) => `${e.title} ${e.detail ?? ""}`).join(" ");
  const fullText = (full.json?.entries ?? []).map((e) => `${e.title} ${e.detail ?? ""}`).join(" ");
  check("DEC-14", "no screening answer, sensitive label, narrative, explanation or evidence detail is repeated in the history",
    heldText.includes("2 screening answers") && SCREENING_LABELS.every((label) => !heldText.includes(label)) &&
      !fullText.includes(NARRATIVE) && !fullText.includes("Notes were taken") && !fullText.includes(EVIDENCE) && !fullText.includes(ROLE),
    heldText.slice(0, 300));

  // ===== The database itself =====
  const asOther = await fixtures.runtimeQuery("SELECT count(*) FROM workflow_decision_records", { company: other.companyId });
  const asOwn = await fixtures.runtimeQuery("SELECT count(*) FROM workflow_decision_records", { company: fed.companyId });
  const tamper = await fixtures.runtimeQuery("UPDATE workflow_decision_records SET summary = 'rewritten'", { company: fed.companyId });
  const remove = await fixtures.runtimeQuery("DELETE FROM workflow_decision_records", { company: fed.companyId });
  const unsafe = await fixtures.runtimeQuery(
    `INSERT INTO workflow_decision_records (id, company_id, instance_id, chain_id, relation, category, summary, explanation, occurred_on,
       decision_maker, evidence_status, evidence, revision, request_key, recorded_by_user_id, definition_version, intake_status, progression_status)
     SELECT x.id, i.company_id, i.id, x.id, 'original', 'formal_warning_issued', 'x', 'x', DATE '2026-10-12', 'recorder', 'none', '[]',
       9999, gen_random_uuid(), ${quote(founderUser)}, 2, 'intake_recorded', 'in_stage'
     FROM workflow_instances i, (SELECT gen_random_uuid() AS id) x WHERE i.case_id = ${quote(caseId)}`,
    { company: fed.companyId },
  );
  check("DEC-15", "as the API's own login: RLS hides the records from another Company; they can't be rewritten or deleted; an unsafe category is refused",
    asOther.ok && asOther.rows[0][0] === "0" && asOwn.ok && Number(asOwn.rows[0][0]) >= 7 && !tamper.ok && !remove.ok &&
      /permission denied/.test(tamper.error) && /permission denied/.test(remove.error) && !unsafe.ok && /ck_workflow_decision_records_category/.test(unsafe.error),
    JSON.stringify({ asOther, asOwn, tamper: tamper.error, unsafe: unsafe.error }).slice(0, 300));

  await page.close();
  const logs = `${ctx.api.logs()}\n${ctx.web.logs()}`;
  check("DEC-16", "no summary, explanation, named role, evidence or reason appears in the API or web logs; records are logged by relation only",
    logs.includes("Workflow decision recorded") && logs.includes("relation=correction") &&
      ![SUMMARY, "handovers.", ROLE, EVIDENCE, "HR-E2E-014", REASON, "Specialist review done"].some((value) => logs.includes(value)));

  const generated = await owner(`SELECT count(*) FROM pg_tables WHERE schemaname = 'public'
    AND (tablename LIKE '%document%' OR tablename LIKE '%penalt%' OR tablename LIKE '%warning%' OR tablename LIKE '%sanction%')`);
  const notAvailable = (await view(caseId)).json?.not_available ?? [];
  check("DEC-17", "nothing generates a document or a penalty: no such table exists and both stay listed as not available",
    generated[0][0] === "0" && notAvailable.includes("Issuing documents") && notAvailable.includes("Penalty and outcome decisions"),
    `${generated[0][0]} ${JSON.stringify(notAvailable)}`);
}
