// M2-03: workflow progression with the real components together, running the
// fictional synthetic rule bundle the harness installs like a deployment does
// (path + pinned SHA-256). A UAE Federal Company's administrator records the
// intake, records a pathway as their own decision, starts a stage, is refused
// completion until the checklist is answered (missing and "No" answers are
// explained), completes it, reloads, signs out and in (everything persists),
// and fits a phone. Through the API: skipping a stage, stale and replayed
// requests, members and other Companies, an escalation that changed answers
// can't release, an intake hold, and an API without rules (fail closed). The
// database, the logs and the browser assets are checked too. Synthetic data only.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { newFounder, quote } from "./common.mjs";

const TITLE = "[SYNTHETIC E2E] Progression journey";
const NARRATIVE = "[SYNTHETIC E2E] A team member repeatedly missed the shift handover checklist.";
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
// Distinctive synthetic bundle content: it must reach the browser only inside
// the API's per-Case answers, never in the shipped web assets.
const BUNDLE_MARKERS = ["Test stage 1: Check-in conversation", "test_check_in_confirmed", "heroos.rule-bundle", "complete_rules"];

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const owner = (sql) => fixtures.ownerQuery(sql);
  const confirm = (founder, args) => fixtures.operator(["confirm-jurisdiction", "--company", founder.companyId, ...args]);

  const fed = await newFounder(ctx, "progress-fed", {
    company_name: "[SYNTHETIC E2E] Progression Federal Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const other = await newFounder(ctx, "progress-other", {
    company_name: "[SYNTHETIC E2E] Progression Other Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const confirmed = await confirm(fed, ["--jurisdiction", "uae_federal", "--licensing-location", "other", "--licensing-authority", AUTHORITY]);
  const memberSubject = ctx.subject("progress-member");
  const provisioned = await fixtures.operator(["provision", "--company", fed.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  const member = { subject: memberSubject, token: ctx.token(memberSubject) };

  const casesApi = `/companies/${fed.companyId}/workflows/disciplinary/cases`;
  const newCase = async (title, screening = "no") => {
    const id = (await ctx.apiFetch(casesApi, { token: fed.token, method: "POST", body: { title, request_key: crypto.randomUUID() } })).json?.id;
    const save = (step, answers, revision) =>
      ctx.apiFetch(`/companies/${fed.companyId}/cases/${id}/workflow/steps/${step}/answers`, {
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
  const recorded = await newCase(TITLE);
  const caseId = recorded.id;
  const caseSql = quote(caseId);
  check("PROG-0", "fixtures: a confirmed UAE Federal Company with a recorded intake, a member, and another Company",
    confirmed.code === 0 && provisioned.code === 0 && recorded.view?.status?.code === "intake_recorded" &&
      recorded.view?.progression?.status?.code === "awaiting_pathway" && recorded.view?.progression?.rules?.provenance === "synthetic",
    JSON.stringify(recorded.view?.progression?.status));

  const events = () =>
    owner(`SELECT e.kind, e.transition, e.decision, e.bundle_version FROM workflow_progress_events e
      JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${caseSql} ORDER BY e.revision, e.occurred_at`);
  const casePath = `/workspaces/${fed.companyId}/cases/${caseId}`;
  const nextSteps = (page) => page.eval(`document.getElementById("next-steps").innerText`);

  // ===== Browser: pathway, stage, checklist, completion (1440 wide) =====
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#pathway-less_serious");
  const opened = await nextSteps(page);
  const recordDisabled = await page.eval(`[...document.querySelectorAll("#next-steps button")].find((b) => b.textContent.trim() === "Record my decision").disabled`);
  check("PROG-1", "the recorded intake offers the employer's own pathway choice, announces the synthetic test rules and suggests nothing",
    opened.includes("Synthetic test rules") && opened.includes("Less serious") && opened.includes("Serious misconduct") &&
      opened.includes("Unable to determine: needs review") && opened.includes("doesn't classify the incident, suggest a pathway") &&
      recordDisabled === true,
    opened.slice(0, 300));
  await ctx.screenshot(page, "progression-pathway-1440");

  await page.click("#pathway-less_serious");
  await page.clickText("#next-steps button", "Record my decision");
  await page.waitForText("(your decision)");
  await page.waitForText("Start this stage");
  const chosen = await nextSteps(page);
  check("PROG-2", "the choice is recorded as the employer's decision and only the first stage can start",
    chosen.includes("Less serious") && chosen.includes("Test stage 1: Check-in conversation") && chosen.includes("Start this stage") &&
      !chosen.includes("Start: Test stage 2"),
    chosen.slice(0, 300));

  await page.clickText("#next-steps button", "Start this stage");
  await page.waitForText("Save checklist");
  const started = await nextSteps(page);
  const completeButton = () => page.eval(`[...document.querySelectorAll("#next-steps button")].some((b) => b.textContent.trim() === "Mark this stage complete")`);
  check("PROG-3", "in the stage, completion is refused until the checklist is answered: what's missing is listed and no button is offered",
    started.includes("In progress") && started.includes("Checklist not complete") && started.includes("Still needed") &&
      started.includes("Test check-in held") && (await completeButton()) === false,
    started.slice(0, 400));

  await page.click(radio("progress.test_check_in.conversation_held", "yes"));
  await page.click(radio("progress.test_check_in.employee_heard", "no"));
  await page.clickText("button", "Save checklist");
  // Saved once the checklist is complete: only the requirement itself is still unmet.
  await page.waitFor(`(() => { const text = document.getElementById("next-steps").innerText;
    return text.includes("Your answers are saved to this case.") && !text.includes("Checklist not complete"); })()`, { message: "checklist saved" });
  const unmet = await nextSteps(page);
  check("PROG-4", "a \"No\" answer doesn't meet the stage requirement: explained, still no way to complete",
    unmet.includes("Test requirement not met") && unmet.includes("Provisional: not legal advice") && (await completeButton()) === false,
    unmet.slice(0, 300));

  await page.click(radio("progress.test_check_in.employee_heard", "yes"));
  await page.clickText("button", "Save checklist");
  await page.waitFor(`[...document.querySelectorAll("#next-steps button")].some((b) => b.textContent.trim() === "Mark this stage complete")`, { message: "complete offered" });
  await page.clickText("#next-steps button", "Mark this stage complete");
  await page.waitForText("Stage completed: Test stage 1");
  const completed = await nextSteps(page);
  const stored = await events();
  check("PROG-5", "with the requirement met the stage completes; the next stage becomes available; PostgreSQL holds the events with the bundle version",
    completed.includes("Completed") && completed.includes("Start this stage") &&
      JSON.stringify(stored.map((row) => row[0])) === JSON.stringify(["pathway_selected", "stage_started", "stage_completed"]) &&
      stored.every((row) => row[3] === "synthetic.1"),
    JSON.stringify(stored));
  await ctx.screenshot(page, "progression-stage-1440");

  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Next steps");
  await page.clickText("button", "Sign out");
  await page.waitFor(`location.origin === ${JSON.stringify(webOrigin)} && location.pathname === "/"`, { message: "signed out" });
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  // (Section headings are upper-cased by CSS, so wait for the section itself.)
  // M2-04: progression events are in the unified case history ("Decisions & history").
  await page.waitFor(`Boolean(document.querySelector('section[aria-labelledby="history-heading"]'))`, { message: "case history" });
  const history = await page.eval(`document.querySelector('section[aria-labelledby="history-heading"]').innerText`);
  const header = await page.eval(`document.querySelector('[data-testid="current-stage"]').innerText`);
  check("PROG-6", "after a reload and a new sign-in the pathway, the stages and the progression history are all still there",
    history.includes("Pathway recorded: Less serious (your decision)") && history.includes("Stage started: Test stage 1") &&
      history.includes("Stage completed: Test stage 1") && header.includes("Ready for the next stage"),
    `${header} | ${history.slice(0, 300)}`);

  await page.viewport(390, 844);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForText("Next steps");
  const overflow = await page.overflow();
  check("PROG-7", "the next steps fit a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await ctx.screenshot(page, "progression-390");
  await page.viewport(1440, 900);

  // ===== API: skipping, stale and replayed requests, access =====
  const view = () => ctx.apiFetch(`/companies/${fed.companyId}/cases/${caseId}/workflow`, { token: fed.token });
  const move = (token, company, transition, revision, key = crypto.randomUUID(), acknowledged = []) =>
    ctx.apiFetch(`/companies/${company}/cases/${caseId}/workflow/progression/transitions`, {
      token, method: "POST", body: { expected_revision: revision, request_key: key, transition, acknowledged_warnings: acknowledged },
    });
  const checklistSave = (step, answers, revision) =>
    ctx.apiFetch(`/companies/${fed.companyId}/cases/${caseId}/workflow/steps/${step}/answers`, {
      token: fed.token, method: "PUT", body: { expected_revision: revision, submission_key: crypto.randomUUID(), answers },
    });
  let revision = (await view()).json?.workflow?.revision;
  const skip = await move(fed.token, fed.companyId, "start:test_final_review", revision);
  const afterSkip = await events();
  check("PROG-8", "skipping to a later stage is refused and recorded; nothing moves",
    skip.status === 200 && skip.json?.progression?.attempt?.outcome === "rejected" && skip.json?.workflow?.revision === revision &&
      afterSkip.at(-1)[0] === "transition_rejected" && afterSkip.at(-1)[1] === "start:test_final_review",
    `${skip.status} ${skip.json?.progression?.attempt?.outcome}`);

  const key = crypto.randomUUID();
  const started2 = await move(fed.token, fed.companyId, "start:test_written_note", revision, key);
  const replayed = await move(fed.token, fed.companyId, "start:test_written_note", revision, key);
  const stale = await move(fed.token, fed.companyId, "complete:test_written_note", revision);
  const startedCount = (await events()).filter((row) => row[1] === "start:test_written_note").length;
  check("PROG-9", "a retried request is applied once with the same answer; a stale revision is a conflict",
    started2.json?.progression?.attempt?.outcome === "applied" && replayed.status === 200 &&
      replayed.json?.workflow?.revision === started2.json?.workflow?.revision && startedCount === 1 && stale.status === 409,
    `${started2.status} ${replayed.status} ${stale.status} ${startedCount}`);
  revision = started2.json?.workflow?.revision;

  const memberMove = await move(member.token, fed.companyId, "complete:test_written_note", revision);
  const memberView = await ctx.apiFetch(`/companies/${fed.companyId}/cases/${caseId}/workflow`, { token: member.token });
  const otherMove = await move(other.token, other.companyId, "complete:test_written_note", revision);
  const otherView = await ctx.apiFetch(`/companies/${other.companyId}/cases/${caseId}/workflow`, { token: other.token });
  check("PROG-10", "a member can neither read nor move the case (403); another Company's administrator can't find it (404)",
    memberMove.status === 403 && memberView.status === 403 && otherMove.status === 404 && otherView.status === 404,
    `${memberMove.status} ${memberView.status} ${otherMove.status} ${otherView.status}`);

  // ===== An escalation changed answers can't release =====
  let saved = await checklistSave("test_written_note", { "progress.test_written_note.note_shared": "yes" }, revision);
  const completeNote = await move(fed.token, fed.companyId, "complete:test_written_note", saved.json?.workflow?.revision);
  const startReview = await move(fed.token, fed.companyId, "start:test_final_review", completeNote.json?.workflow?.revision);
  saved = await checklistSave("test_final_review", {
    "progress.test_final_review.review_done": "yes", "progress.test_final_review.outside_help_needed": "yes",
  }, startReview.json?.workflow?.revision);
  const changed = await checklistSave("test_final_review", { "progress.test_final_review.outside_help_needed": "no" }, saved.json?.workflow?.revision);
  const escalatedAction = (changed.json?.progression?.actions ?? []).find((a) => a.key === "complete:test_final_review");
  const blocked = await move(fed.token, fed.companyId, "complete:test_final_review", changed.json?.workflow?.revision, crypto.randomUUID(), ["earlier_escalation"]);
  const escalations = (await events()).filter((row) => row[0] === "escalation_recorded");
  check("PROG-11", "an escalation is recorded when the answer is saved, and neither a changed answer nor an acknowledgment releases it",
    completeNote.json?.progression?.attempt?.outcome === "applied" && startReview.json?.progression?.attempt?.outcome === "applied" &&
      escalatedAction?.decision === "escalate" && escalatedAction?.allowed === false &&
      blocked.json?.progression?.attempt?.decision === "escalate" && blocked.json?.progression?.status?.code === "in_stage" &&
      escalations.length === 1 && changed.json?.progression?.escalations?.length === 1,
    `${escalatedAction?.decision} ${blocked.json?.progression?.attempt?.decision} ${escalations.length}`);

  // ===== An intake hold blocks progression =====
  const held = await newCase("[SYNTHETIC E2E] Progression held", "no");
  const heldScreening = await ctx.apiFetch(`/companies/${fed.companyId}/cases/${held.id}/workflow/steps/safety_screening/answers`, {
    token: fed.token, method: "PUT",
    body: { expected_revision: held.view?.workflow?.revision, submission_key: crypto.randomUUID(), answers: { "screening.whistleblower": "yes" } },
  });
  const heldChoice = await ctx.apiFetch(`/companies/${fed.companyId}/cases/${held.id}/workflow/progression/pathway`, {
    token: fed.token, method: "POST",
    body: { expected_revision: heldScreening.json?.workflow?.revision, request_key: crypto.randomUUID(), pathway: "less_serious" },
  });
  check("PROG-12", "a specialist-review hold from the intake escalates every transition: the pathway isn't recorded",
    heldScreening.json?.status?.code === "held_for_specialist_review" && heldChoice.json?.progression?.gate?.code === "case_held" &&
      heldChoice.json?.progression?.attempt?.decision === "escalate" && heldChoice.json?.progression?.pathway === null,
    `${heldScreening.json?.status?.code} ${heldChoice.json?.progression?.attempt?.decision}`);

  // ===== An API without rules fails closed =====
  const noRules = ctx.makeApi({ databaseUrl: ctx.urls.runtime(process.env.E2E_DATABASE), label: "api-no-rules" });
  await noRules.start({ rules: false });
  const viaNoRules = (path, init = {}) =>
    fetch(`${noRules.url}${path}`, { ...init, headers: { Authorization: `Bearer ${fed.token}`, "Content-Type": "application/json", ...(init.headers ?? {}) } });
  const before = (await events()).length;
  const noRulesView = await (await viaNoRules(`/companies/${fed.companyId}/cases/${caseId}/workflow`)).json();
  const noRulesMove = await viaNoRules(`/companies/${fed.companyId}/cases/${caseId}/workflow/progression/transitions`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: noRulesView.workflow?.revision, request_key: crypto.randomUUID(), transition: "complete:test_final_review" }),
  });
  await noRules.stop();
  check("PROG-13", "an API without installed rules says progression isn't available, refuses every request (409) and records nothing",
    noRulesView.progression?.status?.code === "unavailable" && noRulesView.progression?.gate?.code === "rules_unavailable" &&
      noRulesView.progression?.actions?.length === 0 && noRulesMove.status === 409 && (await events()).length === before,
    `${noRulesView.progression?.status?.code} ${noRulesMove.status}`);

  // ===== The database itself =====
  const asOther = await fixtures.runtimeQuery(`SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${caseSql}`, { company: other.companyId });
  const asOwn = await fixtures.runtimeQuery(`SELECT count(*) FROM workflow_progress_events e JOIN workflow_instances i ON i.id = e.instance_id WHERE i.case_id = ${caseSql}`, { company: fed.companyId });
  const tamper = await fixtures.runtimeQuery("UPDATE workflow_progress_events SET decision = 'allow'", { company: fed.companyId });
  const remove = await fixtures.runtimeQuery("DELETE FROM workflow_progress_events", { company: fed.companyId });
  check("PROG-14", "as the API's own login, RLS hides the progress events from another Company, and they can be neither rewritten nor deleted",
    asOther.ok && asOther.rows[0][0] === "0" && asOwn.ok && Number(asOwn.rows[0][0]) >= 8 && !tamper.ok && !remove.ok &&
      /permission denied/.test(tamper.error) && /permission denied/.test(remove.error),
    JSON.stringify({ asOther, asOwn, tamper, remove }).slice(0, 300));

  await page.close();
  const logs = `${ctx.api.logs()}\n${ctx.web.logs()}`;
  check("PROG-15", "no title, narrative, stage, rule or answer appears in the API or web logs; progression is logged by kind and decision only",
    !logs.includes(NARRATIVE.slice(16, 60)) && !logs.includes("Progression journey") && !/Test stage|test_check_in|test_outside_help/.test(logs) &&
      logs.includes("Workflow progression stage_completed") && logs.includes("Workflow progression rules loaded"));

  const staticDir = join(ctx.repoRoot, "apps/web/.next/static");
  const assets = files(staticDir).filter((path) => /\.(js|css|html|json|txt|map)$/.test(path));
  const leaks = assets.filter((path) => {
    const text = readFileSync(path, "utf8");
    return BUNDLE_MARKERS.some((marker) => text.includes(marker));
  });
  check("PROG-16", "the browser assets carry no rule content: stages and rules reach the browser only in the API's answer for one Case",
    assets.length > 0 && leaks.length === 0, `${assets.length} assets; leaks: ${leaks.join(", ")}`);
}
