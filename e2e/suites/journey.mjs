// M2-05: one complete synthetic Disciplinary journey through the real product
// (browser → BFF → API → PostgreSQL with RLS), with the fictional synthetic
// rules and templates installed the way a deployment installs private
// bundles. It connects every M2 feature in one case, in the order an employer
// meets them, and takes the screenshots of the founder demo storyboard
// ("journey-NN-*"): sign in and choose the company, start a case, the guided
// intake, the jurisdiction, HeroOS's checks and cautions, the employer's own
// pathway choice (with an acknowledged caution), stages that can't be skipped
// or completed early, a factual employer record, the unified history, a
// document preview at the stage it belongs to, a specialist-review hold that
// stops everything, persistence after a reload and a new sign-in, and a phone.
// Then what the product refuses, checked against the real API and database.
// Synthetic data only: no rule or template here is HeroOS or legal guidance.
import { newFounder, quote } from "./common.mjs";

const AUTHORITY = "[SYNTHETIC DEMO] Free Zone Authority";
const COMPANY = "[SYNTHETIC DEMO] Example Trading LLC";
const TITLE = "[SYNTHETIC DEMO] Repeated late shift handovers";
const NARRATIVE =
  "[SYNTHETIC DEMO] A team member (Sam Example, fictional) missed the shift handover checklist three times in two weeks.";
const SUMMARY = "[SYNTHETIC DEMO] Check-in meeting held with the team member";
const EXPLANATION = "[SYNTHETIC DEMO] The supervisor met Sam Example about the handovers. Notes were taken.";
const PREVIEW_NAME = "[SYNTHETIC DEMO] Sam Example";
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
  const shot = (page, name, selector) => (selector ? ctx.screenshotOf(page, name, selector) : ctx.screenshot(page, name));

  // ===== The fictional world =====
  const admin = await newFounder(ctx, "journey-admin", {
    company_name: COMPANY,
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const sister = await newFounder(ctx, "journey-sister", {
    company_name: "[SYNTHETIC DEMO] Example Logistics LLC",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const confirmed = await fixtures.operator(["confirm-jurisdiction", "--company", admin.companyId, "--jurisdiction", "uae_federal",
    "--licensing-location", "other", "--licensing-authority", AUTHORITY]);  // prettier-ignore
  // The administrator also belongs to a second company, so the journey starts by choosing one.
  const second = await fixtures.operator(["grant", "--company", sister.companyId, "--issuer", ctx.issuer.issuer], admin.subject);
  const memberSubject = ctx.subject("journey-member");
  const member = await fixtures.operator(["provision", "--company", admin.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  check("JOURNEY-0", "the fictional world: a UAE Federal company confirmed by the operator, its administrator (also in a second company), a member and another company",
    confirmed.code === 0 && second.code === 0 && member.code === 0, JSON.stringify({ confirmed, second, member }).slice(0, 300));

  const companyPath = `/workspaces/${admin.companyId}`;
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  const text = () => page.text();
  const section = (id) => page.eval(`document.getElementById(${JSON.stringify(id)}).innerText`);

  // 1–2. Sign in and choose the company.
  await ctx.signIn(page, admin.subject);
  await page.goto(`${webOrigin}/workspaces`);
  await page.waitForText("Choose a workspace");
  const chooser = await text();
  check("JOURNEY-1", "after signing in, the administrator chooses which company to work in",
    chooser.includes(COMPANY) && chooser.includes("[SYNTHETIC DEMO] Example Logistics LLC"), chooser.slice(0, 300));
  await shot(page, "journey-01-choose-company");
  await page.click(`a[href="${companyPath}"]`);
  await page.waitForText("Open Disciplinary cases");
  const home = await text();
  await shot(page, "journey-02-company-workspace");

  // 3. Start a Disciplinary case.
  await page.click(`a[href="${companyPath}/cases"]`);
  await page.waitFor(`Boolean(document.querySelector('a[href="${companyPath}/cases/new"]'))`, { message: "cases list" });
  await page.click(`a[href="${companyPath}/cases/new"]`);
  await page.waitForHydrated("#case-title");
  await page.type("#case-title", TITLE);
  await page.clickText("button", "Create case");
  await page.waitFor(`/^\\/workspaces\\/[^/]+\\/cases\\/[0-9a-f-]{36}$/.test(location.pathname)`, { message: "the new case opens" });
  await page.waitForHydrated("#q-incident-narrative");
  const caseId = await page.eval("location.pathname.split('/').pop()");
  const casePath = `${companyPath}/cases/${caseId}`;
  const welcome = await text();
  check("JOURNEY-2", "the company workspace opens Disciplinary, and a new case starts a guided (not AI) conversation",
    home.includes("Disciplinary") && welcome.includes("not an AI assistant") && welcome.includes("What happened?"),
    `${home.slice(0, 200)} | ${welcome.slice(0, 200)}`);
  await shot(page, "journey-03-new-case");

  // 4–6. The guided intake, with the jurisdiction confirmed for this case.
  const incidentDay = new Date(Date.now() - 4 * 86_400_000).toISOString().slice(0, 10);
  await page.type("#q-incident-narrative", NARRATIVE);
  await page.type("#q-incident-date", incidentDay);
  await page.click(radio("incident.history", "raised_before"));
  await page.click(radio("incident.discussed_with_employee", "yes"));
  await page.click(radio("incident.evidence_available", "not_sure"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Continue to Employment jurisdiction");
  await page.clickText("button", "Continue to Employment jurisdiction");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("jurisdiction.case_confirmation", "uae_federal"))}))`, { message: "jurisdiction" });
  await page.click(radio("jurisdiction.case_confirmation", "uae_federal"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Jurisdiction confirmed for this case");
  const jurisdiction = await text();
  await shot(page, "journey-04-jurisdiction");
  await page.clickText("button", "Continue to Incident context");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("context.location", "at_work"))}))`, { message: "context" });
  await page.click(radio("context.location", "at_work"));
  // "Raised before" in the initial facts brings a follow-up here.
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio("history.documented_action", "verbal_only"))}))`, { message: "follow-up" });
  await page.click(radio("history.documented_action", "verbal_only"));
  await page.click(radio("history.same_incident_sanction", "no"));
  await page.click(radio("context.policy_awareness", "yes"));
  await page.click(radio("evidence.witnesses", "not_sure"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Continue to Safety screening");
  await page.clickText("button", "Continue to Safety screening");
  await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(radio(SCREENING[0], "no"))}))`, { message: "screening" });
  for (const key of SCREENING) await page.click(radio(key, "no"));
  await page.clickText("button", "Save answers");
  await page.waitForText("Intake recorded");
  const recorded = await text();
  check("JOURNEY-3", "the intake collects the facts, confirms the case jurisdiction against the company's, and records a preliminary (not legal) status after a clear screening",
    jurisdiction.includes("Based on your company's confirmed jurisdiction") && recorded.includes("Intake recorded") &&
      recorded.includes("not a legal assessment") && recorded.includes("Synthetic test rules"),
    recorded.slice(0, 300));
  await shot(page, "journey-05-intake-recorded");

  // 7–8. HeroOS's checks, and the employer's own pathway choice (a caution to acknowledge).
  await page.eval(`document.getElementById("next-steps").scrollIntoView()`);
  await page.waitForHydrated("#pathway-less_serious");
  await page.click("#pathway-less_serious");
  await page.waitFor(`Boolean(document.getElementById("ack-pathway-less_serious"))`, { message: "caution to acknowledge" });
  const caution = await section("next-steps");
  const recordDisabled = await page.eval(`[...document.querySelectorAll("#next-steps button")].find((b) => b.textContent.trim() === "Record my decision").disabled`);
  check("JOURNEY-4", "HeroOS suggests no pathway; choosing one raises a caution the employer must acknowledge before the choice can be recorded",
    caution.includes("doesn't classify the incident") && recordDisabled === true, caution.slice(0, 400));
  await shot(page, "journey-06-pathway-caution", "#next-steps");
  await page.click("#ack-pathway-less_serious");
  await page.clickText("#next-steps button", "Record my decision");
  await page.waitForText("(your decision)");
  await page.waitForText("Start this stage");

  // 9. Stages: in order, never completed early.
  await page.clickText("#next-steps button", "Start this stage");
  await page.waitForText("Save checklist");
  const inStage = await section("next-steps");
  const canComplete = () => page.eval(`[...document.querySelectorAll("#next-steps button")].some((b) => b.textContent.trim() === "Mark this stage complete")`);
  check("JOURNEY-5", "stage 1 starts; it can't be completed until its checklist is answered, and the screen says what is missing",
    inStage.includes("Checklist not complete") && inStage.includes("Still needed") && (await canComplete()) === false, inStage.slice(0, 400));
  await shot(page, "journey-07-stage-blocked", "#next-steps");

  // 12–14. A document at the stage it belongs to: fill, preview, nothing issued.
  await page.waitForHydrated("#documents button");
  const documents = await section("documents");
  await page.clickText("#documents button", "Open");
  await page.waitForText("Instructions for you (not part of the document)");
  await page.type("#document-field-recipient_name", PREVIEW_NAME);
  await page.type("#document-field-document_date", new Date().toISOString().slice(0, 10));
  await page.type("#document-field-meeting_date", incidentDay);
  await page.type("#document-field-discussion_points-0", "[SYNTHETIC DEMO] Arrival times at handover");
  await page.click(`input[name="document-choice-meeting_format"][value="in_person"]`);
  await page.clickText("#documents button", "Show preview");
  await page.waitFor(`Boolean(document.querySelector("#documents article"))`, { message: "preview" });
  const preview = await page.eval(`document.querySelector("#documents article").innerText`);
  const actions = await page.eval(`[...document.querySelectorAll("#documents button, #documents a")].map((e) => e.textContent.trim())`);
  check("JOURNEY-6", "at stage 1 the check-in letter template can be previewed: filled with the typed details, watermarked, gaps visible, and nothing offers to issue, send or download it",
    documents.includes("Synthetic test letter: check-in note") && documents.includes("Not available now") &&
      /PREVIEW — NOT ISSUED/i.test(preview) && preview.includes(PREVIEW_NAME) && preview.includes("not provided") &&
      !actions.some((label) => /issue|send|download|sign|save/i.test(label)),
    `${preview.slice(0, 300)} | ${JSON.stringify(actions)}`);
  await shot(page, "journey-08-document-preview", "#documents");

  // The stage completes once its checklist is met.
  await page.eval(`document.getElementById("next-steps").scrollIntoView()`);
  await page.waitForHydrated(radio("progress.test_check_in.conversation_held", "yes"));
  await page.click(radio("progress.test_check_in.conversation_held", "yes"));
  await page.click(radio("progress.test_check_in.employee_heard", "yes"));
  await page.clickText("button", "Save checklist");
  await page.waitFor(`[...document.querySelectorAll("#next-steps button")].some((b) => b.textContent.trim() === "Mark this stage complete")`, { message: "complete offered" });
  await page.clickText("#next-steps button", "Mark this stage complete");
  await page.waitForText("Stage completed: Test stage 1");

  // 10. A factual employer record, which changes nothing in the workflow.
  const revisionBefore = Number(await fixtures.ownerValue(`SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${quote(caseId)}`));
  await page.clickText("#decisions-history button", "Add a record");
  await page.waitForText("What are you recording?");
  await page.click("#decision-category-meeting_recorded");
  await page.type("#decision-summary", SUMMARY);
  await page.type("#decision-date", incidentDay);
  await page.click("#decision-maker-recorder");
  await page.type("#decision-explanation", EXPLANATION);
  await page.click("#decision-evidence-none");
  await page.clickText("#decisions-history button", "Save record");
  await page.waitForText("Record saved");
  const saved = await section("decisions-history");
  const eventsAfter = Number(await fixtures.ownerValue(`SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${quote(caseId)}`));
  check("JOURNEY-7", "the employer records a factual decision; it is saved as the employer's account, and the workflow is unchanged (no progress event added)",
    saved.includes("The workflow hasn't changed") && saved.includes(SUMMARY) && eventsAfter === revisionBefore,
    `${eventsAfter} vs ${revisionBefore}`);
  await shot(page, "journey-09-employer-record", "#decisions-history");

  // Stage 2: its template needs its own checklist answer; its completion carries a caution.
  await page.eval(`document.getElementById("next-steps").scrollIntoView()`);
  await page.waitForHydrated("#next-steps button");
  await page.clickText("#next-steps button", "Start this stage");
  await page.waitForHydrated(radio("progress.test_written_note.note_shared", "yes"));
  await page.waitFor(
    `document.getElementById("documents").innerText.includes("Not available until the information it depends on is answered")`,
    { message: "stage 2 documents" },
  );
  const note = await section("documents");
  check("JOURNEY-8", "at stage 2 its written-note template is shown as not available yet, with the reason, while its precondition is unanswered (unknown never counts)",
    note.includes("At this stage: Test stage 2: Written note") && note.includes("Not available yet") &&
      note.includes("Not available until the information it depends on is answered"), note.slice(0, 400));
  await page.click(radio("progress.test_written_note.note_shared", "yes"));
  await page.clickText("button", "Save checklist");
  await page.waitFor(`Boolean(document.getElementById("ack-complete-test_written_note"))`, { message: "completion caution" });
  await page.waitFor(`document.getElementById("documents").innerText.includes("Synthetic test letter: written note") && !document.getElementById("documents").innerText.includes("Not available until the information")`, { message: "template now available" });
  const completion = await section("next-steps");
  const completeDisabled = await page.eval(`[...document.querySelectorAll("#next-steps button")].find((b) => b.textContent.trim() === "Mark this stage complete").disabled`);
  check("JOURNEY-9", "once answered, the template becomes available; completing the stage raises a caution (evidence not confirmed) that must be acknowledged first",
    completeDisabled === true && completion.includes("Test caution: no supporting evidence confirmed"), completion.slice(0, 400));
  await shot(page, "journey-10-completion-caution", "#next-steps");
  await page.click("#ack-complete-test_written_note");
  await page.clickText("#next-steps button", "Mark this stage complete");
  await page.waitForText("Stage completed: Test stage 2");

  // Stage 3: the employer says outside help is needed → specialist review holds the case.
  await page.clickText("#next-steps button", "Start this stage");
  await page.waitForHydrated(radio("progress.test_final_review.review_done", "yes"));
  await page.click(radio("progress.test_final_review.review_done", "yes"));
  await page.click(radio("progress.test_final_review.outside_help_needed", "yes"));
  await page.clickText("button", "Save checklist");
  await page.waitForText("Specialist review needed");
  const held = await section("next-steps");
  await page.waitFor(`document.getElementById("documents").innerText.includes("on hold for specialist review")`, { message: "documents held" });
  const heldDocuments = await section("documents");
  check("JOURNEY-10", "an answer that needs outside help puts the case on hold for specialist review: completion is refused, and no document can be previewed",
    held.includes("Specialist review needed") && !(await canComplete()) && heldDocuments.includes("on hold for specialist review") &&
      heldDocuments.includes("No template can be previewed at this point of the case."),
    `${held.slice(0, 300)} | ${heldDocuments.slice(0, 200)}`);
  await shot(page, "journey-11-specialist-hold", "#next-steps");

  // 11. The unified history.
  const history = await page.eval(`document.querySelector('section[aria-labelledby="history-heading"]').innerText`);
  check("JOURNEY-11", "the case history shows, in one place and in order, every step: creation, answers, checks, the pathway, stages, the employer record and the escalation",
    ["Case created", "Intake recorded", "Pathway recorded: Less serious (your decision)", "Stage started: Test stage 1",
      "Stage completed: Test stage 1", "Employer record: Meeting or discussion recorded", "Stage completed: Test stage 2"]
      .every((entry) => history.includes(entry)) && /Specialist review needed|SPECIALIST REVIEW NEEDED/.test(history),
    history.slice(0, 600));
  await shot(page, "journey-12-history", 'section[aria-labelledby="history-heading"]');

  // Refresh, sign out and in: everything persisted.
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Next steps");
  await page.clickText("button", "Sign out");
  await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/"`, { message: "signed out" });
  await ctx.signIn(page, admin.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitFor(`Boolean(document.querySelector('section[aria-labelledby="history-heading"]'))`, { message: "history after sign-in" });
  const again = await text();
  check("JOURNEY-12", "after a reload and a new sign-in, the stages, the hold, the record and the history are all still there",
    again.includes("Specialist review needed") && again.includes(SUMMARY) && again.includes("Stage completed: Test stage 2"),
    again.slice(0, 300));

  // For the live demo (make demo-synthetic): where to pick up by hand.
  ctx.demo = { subject: admin.subject, casePath, companyPath };

  // 15 (layout). A phone.
  await page.viewport(390, 844);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Next steps");
  const overflow = await page.overflow();
  check("JOURNEY-13", "the whole case page fits a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await shot(page, "journey-13-phone");
  await page.viewport(1440, 900);
  await page.close();

  // ===== 15. What HeroOS refuses (real API and database) =====
  const api = (path, init = {}) => ctx.apiFetch(`/companies/${admin.companyId}/cases/${caseId}${path}`, { token: admin.token, ...init });
  const view = await api("/workflow");
  const revision = view.json?.workflow?.revision;
  const skip = await api("/workflow/progression/transitions", {
    method: "POST", body: { expected_revision: revision, request_key: crypto.randomUUID(), transition: "complete:test_final_review" },
  });
  const unlock = await api("/decisions", {
    method: "POST",
    body: { expected_revision: revision, request_key: crypto.randomUUID(), category: "other_note",
      summary: "[SYNTHETIC DEMO] Specialist review done, hold cleared, stage complete", explanation: "[SYNTHETIC DEMO] Claimed.",
      occurred_on: incidentDay, decision_maker: "recorder", evidence_status: "none" },
  });  // prettier-ignore
  const afterUnlock = await api("/workflow");
  const documentsAfter = await api("/documents");
  const preview2 = await api("/documents/synthetic.written_note/preview", { method: "POST", body: { template_version: 1, values: {}, choices: {} } });
  check("JOURNEY-14", "HeroOS refuses what isn't permitted: completing a held stage is refused (recorded, nothing moves), a record claiming the hold is cleared changes nothing, and no template can be previewed while held",
    skip.json?.progression?.attempt?.outcome === "rejected" && unlock.status === 200 &&
      afterUnlock.json?.progression?.escalations?.length > 0 && afterUnlock.json?.progression?.stages?.some((s) => s.status === "in_progress") &&
      Object.values(documentsAfter.json?.templates ?? [{}]).every((t) => t.reason === "case_held") && preview2.status === 409,
    `${skip.json?.progression?.attempt?.outcome} ${unlock.status} ${preview2.status}`);

  const memberToken = ctx.token(memberSubject);
  const other = await newFounder(ctx, "journey-other", {
    company_name: "[SYNTHETIC DEMO] Unrelated Co.", blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const access = await Promise.all([
    ctx.apiFetch(`/companies/${admin.companyId}/cases/${caseId}/workflow`, { token: memberToken }),
    ctx.apiFetch(`/companies/${admin.companyId}/cases/${caseId}/documents`, { token: memberToken }),
    ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/workflow`, { token: other.token }),
    ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/documents`, { token: other.token }),
  ]);
  check("JOURNEY-15", "an ordinary member can't open the case (403) and another company's administrator can't find it (404)",
    access[0].status === 403 && access[1].status === 403 && access[2].status === 404 && access[3].status === 404,
    access.map((r) => r.status).join(","));

  const stored = await owner(`SELECT
      (SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${quote(caseId)}),
      (SELECT count(*) FROM workflow_decision_records d JOIN workflow_instances i ON i.id = d.instance_id WHERE i.case_id = ${quote(caseId)}),
      (SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE '%document%' OR tablename LIKE '%preview%' OR tablename LIKE '%penalt%' OR tablename LIKE '%sanction%'))`);
  const tables = (await owner("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).map((row) => row[0]);
  let anywhere = 0;
  for (const table of tables) {
    anywhere += Number(await fixtures.ownerValue(`SELECT count(*) FROM ${table} r WHERE strpos(r::text, ${quote(PREVIEW_NAME)}) > 0`));
  }
  check("JOURNEY-16", "PostgreSQL holds the progress events and the two employer records; no document, preview, penalty or sanction table exists, and the previewed name was never stored",
    Number(stored[0][0]) >= 7 && stored[0][1] === "2" && stored[0][2] === "0" && anywhere === 0,
    JSON.stringify(stored));
}
