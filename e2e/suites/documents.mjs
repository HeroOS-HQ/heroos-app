// M2-04C: document templates and safe previews with the real components
// together (synthetic rules and synthetic templates installed as a deployment
// installs them). A UAE Federal Company's administrator, on a Case at a stage
// a template is bound to, sees which templates can be previewed and why the
// others can't, opens one (the Company name suggested from the case, the
// instructions beside the form), previews it with values that look like
// markup and links (shown as text, watermarked, with gaps for what's
// missing), and finds nothing kept: not in the database, the logs, the
// browser's storage, or after a reload. Through the API and the BFF:
// availability following the stage, a hold and a precondition, a decision
// record that unlocks nothing, members and other Companies, validation that
// never echoes, an API without templates, and templates written for other
// rules (startup refused). Synthetic data only.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { newFounder, quote } from "./common.mjs";

const TITLE = "[SYNTHETIC E2E] Documents journey";
const NARRATIVE = "[SYNTHETIC E2E] A team member missed the shift handover twice.";
const AUTHORITY = "[SYNTHETIC E2E] Free Zone Authority";
const COMPANY = "[SYNTHETIC E2E] Documents Federal Co.";
// Unique per run: if it is anywhere afterwards, a preview kept it.
const MARKER = `[SYNTHETIC E2E] Preview marker ${crypto.randomUUID()}`;
const XSS = `<img src=x onerror="window.__e2eXss=1">`;
const LINK = "javascript:window.__e2eXss=2";
const SUMMARY = `${MARKER}\nSecond line ${LINK}`;
const POINT = `${MARKER} point`;
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
// Template wording that must never reach a browser asset or a log.
const WORDING = ["Synthetic test letter", "Test instructions", "refers to a test conversation held on", "heroos.template-bundle"];

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

export async function run(ctx) {
  const { check, fixtures, webOrigin } = ctx;
  const owner = (sql) => fixtures.ownerQuery(sql);
  const confirm = (founder) =>
    fixtures.operator(["confirm-jurisdiction", "--company", founder.companyId, "--jurisdiction", "uae_federal",
      "--licensing-location", "other", "--licensing-authority", AUTHORITY]);  // prettier-ignore

  const fed = await newFounder(ctx, "documents-fed", {
    company_name: COMPANY,
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const other = await newFounder(ctx, "documents-other", {
    company_name: "[SYNTHETIC E2E] Documents Other Co.",
    blueprint: { licensing: { location: "other", authority: AUTHORITY } },
  });
  const confirmed = await confirm(fed);
  const memberSubject = ctx.subject("documents-member");
  const provisioned = await fixtures.operator(["provision", "--company", fed.companyId, "--issuer", ctx.issuer.issuer], memberSubject);
  const member = { token: ctx.token(memberSubject) };

  const caseApi = (id, path = "", company = fed.companyId) => `/companies/${company}/cases/${id}${path}`;
  const newCase = async (title, screening = "no") => {
    const id = (await ctx.apiFetch(`/companies/${fed.companyId}/workflows/disciplinary/cases`, {
      token: fed.token, method: "POST", body: { title, request_key: crypto.randomUUID() },
    })).json?.id;
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
    return { id, view: last.json, save };
  };
  const pathway = (id, revision, choice = "less_serious") =>
    ctx.apiFetch(caseApi(id, "/workflow/progression/pathway"), {
      token: fed.token, method: "POST", body: { expected_revision: revision, request_key: crypto.randomUUID(), pathway: choice },
    });
  const move = (id, revision, transition) =>
    ctx.apiFetch(caseApi(id, "/workflow/progression/transitions"), {
      token: fed.token, method: "POST", body: { expected_revision: revision, request_key: crypto.randomUUID(), transition },
    });
  const list = (id, token = fed.token, company = fed.companyId) => ctx.apiFetch(caseApi(id, "/documents", company), { token });
  const form = (id, key, token = fed.token, company = fed.companyId) => ctx.apiFetch(caseApi(id, `/documents/${key}`, company), { token });
  const preview = (id, key, body, token = fed.token, company = fed.companyId) =>
    ctx.apiFetch(caseApi(id, `/documents/${key}/preview`, company), { token, method: "POST", body: { template_version: 1, values: {}, choices: {}, ...body } });
  const reasons = (response) => Object.fromEntries((response.json?.templates ?? []).map((t) => [t.key, t.reason]));

  // A Case with the intake recorded and stage 1 of the less serious pathway in progress.
  const recorded = await newCase(TITLE);
  const caseId = recorded.id;
  const chosen = await pathway(caseId, recorded.view?.workflow?.revision);
  const started = await move(caseId, chosen.json?.workflow?.revision, "start:test_check_in");
  const firstList = await list(caseId);
  check("DOCS-0", "fixtures: a confirmed UAE Federal Company, a Case at a stage with a template, a member and another Company",
    confirmed.code === 0 && provisioned.code === 0 && started.json?.progression?.status?.code === "in_stage" &&
      firstList.status === 200 && reasons(firstList)["synthetic.check_in_note"] === null,
    JSON.stringify(reasons(firstList)));

  const instanceRevision = () =>
    fixtures.ownerValue(`SELECT revision FROM workflow_instances WHERE case_id = ${quote(caseId)}`);
  const tables = (await owner("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")).map((row) => row[0]);
  const snapshot = async () => {
    const counts = {};
    let found = 0;
    for (const table of tables) {
      counts[table] = await fixtures.ownerValue(`SELECT count(*) FROM ${table}`);
      found += Number(await fixtures.ownerValue(`SELECT count(*) FROM ${table} r WHERE strpos(r::text, ${quote(MARKER)}) > 0`));
    }
    return { counts: JSON.stringify(counts), found };
  };
  const before = await snapshot();
  const revisionBefore = await instanceRevision();
  const casePath = `/workspaces/${fed.companyId}/cases/${caseId}`;
  const section = (page) => page.eval(`document.getElementById("documents").innerText`);

  // ===== Browser (1440 wide) =====
  const page = await ctx.newPage();
  await page.viewport(1440, 900);
  await ctx.signIn(page, fed.subject);
  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#documents button");
  const opened = await section(page);
  check("DOCS-1", "the case shows Documents: the template for this stage, why the four others can't be previewed, and that the templates are synthetic and provisional",
    opened.includes("Synthetic test letter: check-in note") && opened.includes("Synthetic test templates") &&
      opened.includes("Template wording here is provisional") && opened.includes("Not available now (4)") &&
      opened.includes("HeroOS doesn't save, send or issue them"),
    opened.slice(0, 400));
  await ctx.screenshotOf(page, "documents-list-1440", "#documents");

  await page.clickText("#documents button", "Open");
  await page.waitForText("Instructions for you (not part of the document)");
  const formText = await section(page);
  const suggested = await page.eval(`document.getElementById("document-field-company_name").value`);
  const autocomplete = await page.eval(`document.querySelector("#documents form").getAttribute("autocomplete")`);
  check("DOCS-2", "the form opens with the Company name suggested from the case, the employer instructions beside it, the privacy notice and the reminder; autofill is off",
    suggested === COMPANY && formText.includes("[SYNTHETIC] Test instructions") && formText.includes("Nothing you type here is saved") &&
      formText.includes("Leave out health, family, religion") && autocomplete === "off",
    `${suggested} ${autocomplete}`);

  await page.type("#document-field-recipient_name", XSS);
  await page.type("#document-field-discussion_points-0", POINT);
  await page.type("#document-field-summary", SUMMARY);
  await page.type("#document-field-document_date", "2026-10-18");
  await page.click(`input[name="document-choice-meeting_format"][value="online"]`);
  await ctx.screenshotOf(page, "documents-form-1440", "#documents");
  await page.clickText("#documents button", "Show preview");
  await page.waitFor(`Boolean(document.querySelector("#documents article"))`, { message: "preview" });
  const article = await page.eval(`(() => {
    const a = document.querySelector("#documents article");
    return {
      text: a.innerText,
      elements: a.querySelectorAll("script, img, a, iframe, object, embed, form").length,
      watermarks: a.querySelectorAll("[data-watermark]").length,
      xss: window.__e2eXss ?? null,
    };
  })()`);
  check("DOCS-3", "the preview shows what was typed as plain text (no element, link or script from it), watermarked at the top, the bottom and on every printed page, with gaps for what's missing",
    article.elements === 0 && article.xss === null && article.watermarks === 3 && article.text.includes(XSS) &&
      article.text.includes(MARKER) && article.text.includes(LINK) && /PREVIEW — NOT ISSUED/i.test(article.text) &&
      article.text.includes("Template wording: provisional, not approved for use.") &&
      article.text.includes("18 October 2026") && article.text.includes("took place online.") &&
      article.text.includes("[Date of the test conversation: not provided]"),
    JSON.stringify({ ...article, text: article.text.slice(0, 300) }));
  await ctx.screenshotOf(page, "documents-preview-1440", "#documents");

  const after = await snapshot();
  const storage = await page.eval(`localStorage.length + sessionStorage.length`);
  check("DOCS-4", "nothing was kept: no row anywhere in the database holds a previewed value, no table changed, the case's revision is unchanged and the browser stored nothing",
    before.found === 0 && after.found === 0 && after.counts === before.counts && (await instanceRevision()) === revisionBefore && storage === 0,
    `found ${after.found}, revision ${revisionBefore}, storage ${storage}`);

  await page.goto(`${webOrigin}${casePath}`);
  await page.waitForHydrated("#documents button");
  await page.clickText("#documents button", "Open");
  await page.waitForText("Instructions for you (not part of the document)");
  const reopened = await page.eval(`({
    name: document.getElementById("document-field-recipient_name").value,
    summary: document.getElementById("document-field-summary").value,
    preview: Boolean(document.querySelector("#documents article")),
  })`);
  check("DOCS-5", "after a reload the draft and the preview are gone: nothing typed was remembered",
    reopened.name === "" && reopened.summary === "" && reopened.preview === false, JSON.stringify(reopened));

  await page.viewport(390, 844);
  await page.type("#document-field-summary", SUMMARY);
  await page.clickText("#documents button", "Show preview");
  await page.waitFor(`Boolean(document.querySelector("#documents article"))`, { message: "preview at 390" });
  const overflow = await page.overflow();
  check("DOCS-6", "the form and the preview fit a 390 px phone without horizontal scrolling", overflow <= 0, `overflow ${overflow}px`);
  await ctx.screenshotOf(page, "documents-preview-390", "#documents");
  await page.viewport(1440, 900);
  await page.close();

  // ===== Availability follows the case, server-side =====
  const done = await ctx.apiFetch(caseApi(caseId, "/workflow/steps/test_check_in/answers"), {
    token: fed.token, method: "PUT",
    body: { expected_revision: started.json?.workflow?.revision, submission_key: crypto.randomUUID(),
      answers: { "progress.test_check_in.conversation_held": "yes", "progress.test_check_in.employee_heard": "yes" } },
  });  // prettier-ignore
  const completed = await move(caseId, done.json?.workflow?.revision, "complete:test_check_in");
  const afterStage = await list(caseId);
  const stalePreview = await preview(caseId, "synthetic.check_in_note", {});
  const note = await move(caseId, completed.json?.workflow?.revision, "start:test_written_note");
  const unknown = await list(caseId);
  const answer = (value, revision) =>
    ctx.apiFetch(caseApi(caseId, "/workflow/steps/test_written_note/answers"), {
      token: fed.token, method: "PUT",
      body: { expected_revision: revision, submission_key: crypto.randomUUID(), answers: { "progress.test_written_note.note_shared": value } },
    });
  const no = await answer("no", note.json?.workflow?.revision);
  const notMet = await list(caseId);
  const yes = await answer("yes", no.json?.workflow?.revision);
  const met = await list(caseId);
  check("DOCS-7", "availability follows the stage and its checklist: a completed stage's template is gone (409), an unanswered precondition is unknown, a 'no' is not met, a 'yes' opens it",
    reasons(afterStage)["synthetic.check_in_note"] === "not_at_this_stage" && stalePreview.status === 409 &&
      reasons(unknown)["synthetic.written_note"] === "requirement_unknown" && reasons(notMet)["synthetic.written_note"] === "requirement_not_met" &&
      yes.status === 200 && reasons(met)["synthetic.written_note"] === null &&
      reasons(met)["synthetic.specialist_letter"] === "specialist_review_required" && reasons(met)["synthetic.difc_note"] === "not_for_jurisdiction",
    JSON.stringify({ afterStage: reasons(afterStage), unknown: reasons(unknown), notMet: reasons(notMet), met: reasons(met) }));

  // ===== A hold, and a decision record that unlocks nothing =====
  const held = await newCase("[SYNTHETIC E2E] Documents held", "no");
  const heldSave = await held.save("safety_screening", { "screening.whistleblower": "yes" }, held.view?.workflow?.revision);
  const heldList = await list(held.id);
  const unready = await newCase("[SYNTHETIC E2E] Documents unready");
  const recordedNote = await ctx.apiFetch(caseApi(unready.id, "/decisions"), {
    token: fed.token, method: "POST",
    body: { expected_revision: unready.view?.workflow?.revision, request_key: crypto.randomUUID(), category: "meeting_recorded",
      summary: "[SYNTHETIC E2E] Check-in held, stage done", explanation: "[SYNTHETIC E2E] Noted.", occurred_on: "2026-10-12",
      decision_maker: "recorder", evidence_status: "none" },
  });  // prettier-ignore
  const unreadyList = await list(unready.id);
  check("DOCS-8", "a case held for specialist review offers nothing; a decision record (even one claiming the stage is done) makes no template available",
    heldSave.json?.status?.code === "held_for_specialist_review" && Object.values(reasons(heldList)).every((r) => r === "case_held") &&
      recordedNote.status === 200 && Object.values(reasons(unreadyList)).every((r) => r !== null) &&
      (await preview(unready.id, "synthetic.check_in_note", {})).status === 409,
    JSON.stringify({ held: reasons(heldList), unready: reasons(unreadyList) }));

  // ===== Access =====
  const memberCalls = await Promise.all([
    list(caseId, member.token),
    form(caseId, "synthetic.written_note", member.token),
    preview(caseId, "synthetic.written_note", {}, member.token),
  ]);
  const otherCalls = await Promise.all([
    list(caseId, other.token, other.companyId),
    form(caseId, "synthetic.written_note", other.token, other.companyId),
    preview(caseId, "synthetic.written_note", {}, other.token, other.companyId),
  ]);
  const anonymous = await ctx.apiFetch(caseApi(caseId, "/documents"), {});
  check("DOCS-9", "a member is refused (403), another Company's administrator can't find the case (404), and no token is refused (401)",
    memberCalls.every((r) => r.status === 403) && otherCalls.every((r) => r.status === 404) && anonymous.status === 401,
    `${memberCalls.map((r) => r.status)} ${otherCalls.map((r) => r.status)} ${anonymous.status}`);

  // ===== The BFF =====
  const session = ctx.session(fed.token);
  const bffBase = `/bff/companies/${fed.companyId}/cases/${caseId}/documents`;
  const bffList = await ctx.webFetch(bffBase, { session, headers: { "Sec-Fetch-Site": "same-origin" } });
  const bffCross = await ctx.webFetch(bffBase, { session, headers: { "Sec-Fetch-Site": "cross-site" } });
  const bffQuery = await ctx.webFetch(`${bffBase}?name=x`, { session, headers: { "Sec-Fetch-Site": "same-origin" } });
  const bffNoSession = await ctx.webFetch(bffBase, { headers: { "Sec-Fetch-Site": "same-origin" } });
  const previewPath = `${bffBase}/synthetic.written_note/preview`;
  const sameOrigin = { Origin: webOrigin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
  const bffPreview = await ctx.webFetch(previewPath, {
    method: "POST", session, headers: sameOrigin, body: JSON.stringify({ templateVersion: 1, values: { summary: MARKER }, choices: {} }),
  });
  const bffForeign = await ctx.webFetch(previewPath, {
    method: "POST", session, headers: { ...sameOrigin, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" },
    body: JSON.stringify({ templateVersion: 1, values: {}, choices: {} }),
  });
  const bffForm = await ctx.webFetch(previewPath, {
    method: "POST", session, headers: { ...sameOrigin, "Content-Type": "application/x-www-form-urlencoded" }, body: "templateVersion=1",
  });
  const bffLarge = await ctx.webFetch(previewPath, {
    method: "POST", session, headers: sameOrigin, body: JSON.stringify({ templateVersion: 1, values: { summary: "x".repeat(40_000) }, choices: {} }),
  });
  check("DOCS-10", "the BFF reads for a same-origin session only, takes no query, and guards the preview: foreign origin 403, form post 415, oversized 413; a valid preview is never cached",
    bffList.status === 200 && bffList.json?.documents?.templates?.length === 5 && bffCross.status === 403 && bffQuery.status === 422 &&
      bffNoSession.status === 401 && bffPreview.status === 200 && bffPreview.headers?.get?.("cache-control") === "no-store" &&
      bffForeign.status === 403 && bffForm.status === 415 && bffLarge.status === 413,
    `${bffList.status} ${bffCross.status} ${bffQuery.status} ${bffNoSession.status} ${bffPreview.status} ${bffForeign.status} ${bffForm.status} ${bffLarge.status}`);

  // ===== Validation never echoes; a changed version is a conflict =====
  const refused = await Promise.all([
    preview(caseId, "synthetic.written_note", { values: { recipient_name: `${MARKER}‮` } }),
    preview(caseId, "synthetic.written_note", { values: { document_date: MARKER } }),
    preview(caseId, "synthetic.written_note", { values: { [MARKER.toLowerCase().replace(/[^a-z]/g, "")]: MARKER } }),
    preview(caseId, "synthetic.written_note", { values: { recipient_name: "x".repeat(121) } }),
  ]);
  const version = await preview(caseId, "synthetic.written_note", { template_version: 2 });
  check("DOCS-11", "invalid values are refused (422) without repeating them, and a template version that changed is a conflict (409)",
    refused.every((r) => r.status === 422 && !r.text.includes(MARKER)) && version.status === 409,
    refused.map((r) => r.status).join(","));

  // ===== Without templates, and templates for other rules =====
  const noTemplates = ctx.makeApi({ databaseUrl: ctx.urls.runtime(process.env.E2E_DATABASE), label: "api-no-templates" });
  await noTemplates.start({ templates: false });
  const viaNoTemplates = async (path, init = {}) => {
    const response = await fetch(`${noTemplates.url}${path}`, { ...init, headers: { Authorization: `Bearer ${fed.token}`, "Content-Type": "application/json" } });
    return { status: response.status, json: await response.json().catch(() => null) };
  };
  const withoutList = await viaNoTemplates(caseApi(caseId, "/documents"));
  const withoutPreview = await viaNoTemplates(caseApi(caseId, "/documents/synthetic.written_note/preview"), {
    method: "POST", body: JSON.stringify({ template_version: 1 }),
  });
  await noTemplates.stop();
  const mismatched = ctx.makeApi({ databaseUrl: ctx.urls.runtime(process.env.E2E_DATABASE), label: "api-mismatched-templates" });
  const mismatchedPath = join(ctx.runDir, "mismatched-templates.json");
  const mismatchedBundle = JSON.parse(readFileSync(join(ctx.repoRoot, "apps/api/tests/fixtures/template_bundles/synthetic-disciplinary.json"), "utf8"));
  mismatchedBundle.rule_bundle.versions = ["synthetic.2"];
  writeFileSync(mismatchedPath, JSON.stringify(mismatchedBundle));
  const refusal = await mismatched.startExpectingRefusal({
    extraEnv: {
      HEROOS_TEMPLATE_BUNDLE_PATH: mismatchedPath,
      HEROOS_TEMPLATE_BUNDLE_SHA256: createHash("sha256").update(readFileSync(mismatchedPath)).digest("hex"),
    },
  });
  check("DOCS-12", "an API without templates says so and has none to preview (404); an API given templates written for other rules refuses to start, naming a code, never wording",
    withoutList.status === 200 && withoutList.json?.installed === false && withoutList.json?.templates?.length === 0 &&
      withoutPreview.status === 404 && refusal !== null && refusal.includes("template bundle refused: rule_bundle_mismatch") &&
      !WORDING.slice(0, 3).some((words) => refusal.includes(words)),
    `${withoutList.status} ${withoutPreview.status} ${refusal === null ? "started" : "refused"}`);

  // ===== Logs and browser assets =====
  const logs = `${ctx.api.logs()}\n${ctx.web.logs()}`;
  check("DOCS-13", "no previewed value or template wording appears in the API or web logs; previews are logged by template and outcome only",
    logs.includes("Document preview rendered") && logs.includes("template=synthetic.check_in_note") && logs.includes("Document templates loaded") &&
      !logs.includes(MARKER) && !logs.includes("__e2eXss") && !WORDING.slice(0, 3).some((words) => logs.includes(words)));
  const staticDir = join(ctx.repoRoot, "apps/web/.next/static");
  const assets = files(staticDir).filter((path) => /\.(js|css|html|json|txt|map)$/.test(path));
  const leaks = assets.filter((path) => WORDING.some((words) => readFileSync(path, "utf8").includes(words)));
  check("DOCS-14", "the browser assets carry no template content: a template reaches the browser only in the API's answer for one Case",
    assets.length > 0 && leaks.length === 0, `${assets.length} assets; leaks: ${leaks.join(", ")}`);

  const generated = await owner(`SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE '%document%' OR tablename LIKE '%preview%' OR tablename LIKE '%template%')`);
  check("DOCS-15", "no document, preview or template table exists: previews are never stored", generated[0][0] === "0", generated[0][0]);
}
