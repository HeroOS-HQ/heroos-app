// @vitest-environment node
import { describe, expect, it } from "vitest";

import { ALL_CLEAR, apiCaseSummary, apiView, CASE_ID, HIGH_RISK_HOLD, NARRATIVE, POLICY_CAUTION, view } from "@/test/workflow-fixtures";

import { buildAnswers, draftFrom, isAsked, mergedAnswers } from "./answers";
import { displayAnswer, formatDay, formatDayTime } from "./copy";
import { isWorkflowView, parseCaseSummaries, parseCaseSummary, parseWorkflowView } from "./model";
import { parseAnswersSave, parseCaseCreate } from "./requests";

const UUID_A = "a1b2c3d4-0000-4000-8000-000000000001";

describe("parseWorkflowView", () => {
  it("maps the API's view to the web shape", () => {
    const parsed = parseWorkflowView(apiView({ answers: { "incident.history": "new" }, revision: 3 }));
    expect(parsed).not.toBeNull();
    expect(parsed!.case.id).toBe(CASE_ID);
    expect(parsed!.workflow).toEqual({ key: "disciplinary", title: "Disciplinary", definitionVersion: 2, revision: 3 });
    expect(parsed!.answers).toEqual({ "incident.history": "new" });
    expect(parsed!.answerLabels).toEqual({ "incident.history": "This is a new issue" });
    expect(parsed!.steps.map((s) => [s.key, s.available, s.provisional])).toEqual([
      ["initial_facts", true, false],
      ["jurisdiction", false, false],
      ["incident_context", true, false],
      ["safety_screening", false, true],
    ]);
    expect(parsed!.steps[0].questions.map((q) => q.kind)).toEqual(["text", "date", "choice", "choice", "choice"]);
    expect(parsed!.steps[0].questions[1].allowNotSure).toBe(true);
    expect(parsed!.steps[2].questions[1].askWhen).toEqual({ key: "context.location", values: ["outside_work"] });
    expect(parsed!.asked).not.toContain("context.work_connection");
    expect(parsed!.intake.hold?.reason).toBe("company_jurisdiction_unconfirmed");
    expect(parsed!.history.map((h) => h.kind)).toEqual(["case_created"]);
    expect(parsed!.conversation.map((m) => m.kind)).toEqual([
      "information",
      "question_group",
      "answer_confirmation",
      "status_notice",
      "hold",
      "missing_information",
      "status_notice",
    ]);
  });

  it("allows guidance only for a supported, confirmed jurisdiction", () => {
    const tampered = apiView();
    (tampered.jurisdiction as Record<string, unknown>).guidance_allowed = true;
    expect(parseWorkflowView(tampered)!.jurisdiction.guidanceAllowed).toBe(false);
    expect(parseWorkflowView(apiView({ company: "uae_federal" }))!.jurisdiction.guidanceAllowed).toBe(true);
  });

  it("maps an earlier escalation, the screening setting and a kept hold", () => {
    const parsed = parseWorkflowView(
      apiView({
        company: "uae_federal",
        hold: { ...HIGH_RISK_HOLD, reason: "earlier_escalation" },
        escalation: { since: "2026-10-16T09:00:00Z", reason: "high_risk_factors", current: false },
        history: [{ id: "k", kind: "hold_kept", at: "2026-10-16T09:05:00Z", by_viewer: true, title: "Hold kept after answers changed", detail: null }],
        screening: "disabled",
      }),
    )!;
    expect(parsed.intake.escalation).toEqual({ since: "2026-10-16T09:00:00Z", reason: "high_risk_factors", current: false });
    expect(parsed.intake.hold?.reason).toBe("earlier_escalation");
    expect(parsed.history.map((h) => h.kind)).toEqual(["hold_kept"]);
    expect(parsed.sensitiveScreening).toBe("disabled");
    expect(parsed.steps[3].sensitive).toBe(true);
  });

  it("maps holds and cautions, and never opens the next stage while held", () => {
    const held = apiView({ company: "uae_federal", hold: HIGH_RISK_HOLD, cautions: [POLICY_CAUTION] });
    (held.intake as Record<string, unknown>).next_stage_open = true; // tampered
    const parsed = parseWorkflowView(held)!;
    expect(parsed.intake.hold).toEqual({ ...HIGH_RISK_HOLD, kind: "hold" });
    expect(parsed.intake.cautions).toEqual([POLICY_CAUTION]);
    expect(parsed.intake.nextStageOpen).toBe(false);
    expect(parsed.conversation.filter((m) => m.kind === "hold" || m.kind === "caution").map((m) => m.kind)).toEqual(["hold", "caution"]);
    const recorded = view({
      company: "uae_federal",
      answers: { "jurisdiction.case_confirmation": "uae_federal" },
      status: { code: "intake_recorded", label: "Intake recorded" },
    });
    expect(recorded.intake.caseJurisdiction).toEqual({
      status: "resolved",
      jurisdiction: "uae_federal",
      label: "UAE Federal (MOHRE)",
      companyJurisdiction: "uae_federal",
    });
    expect(recorded.intake.nextStageOpen).toBe(true);
  });

  it("skips message kinds this version doesn't know, but refuses malformed known ones", () => {
    const newer = apiView({ conversation: [{ kind: "decision_card", id: "d1", options: [] }, { kind: "information", id: "i", title: "t", body: "b" }] });
    expect(parseWorkflowView(newer)!.conversation).toEqual([{ kind: "information", id: "i", title: "t", body: "b" }]);
    expect(parseWorkflowView(apiView({ conversation: [{ kind: "information", id: "i", title: 1, body: "b" }] }))).toBeNull();
    expect(
      parseWorkflowView(apiView({ conversation: [{ kind: "status_notice", id: "s", tone: "shouting", title: "t", body: "b" }] })),
    ).toBeNull();
  });

  it.each([
    ["no case", (v: Record<string, unknown>) => delete v.case],
    ["a non-UUID case id", (v: Record<string, unknown>) => ((v.case as Record<string, unknown>).id = "x")],
    ["a negative revision", (v: Record<string, unknown>) => ((v.workflow as Record<string, unknown>).revision = -1)],
    ["a string can_edit", (v: Record<string, unknown>) => (v.can_edit = "yes")],
    ["a non-string answer", (v: Record<string, unknown>) => (v.answers = { "incident.history": 1 })],
    ["an odd answer key", (v: Record<string, unknown>) => (v.answers = { "Incident History": "new" })],
    ["an unknown progress status", (v: Record<string, unknown>) => ((v.progress as Record<string, unknown>[])[0].status = "decided")],
    ["an unknown readiness", (v: Record<string, unknown>) => ((v.jurisdiction as Record<string, unknown>).readiness = "maybe")],
    ["an unknown question kind", (v: Record<string, unknown>) => (((v.steps as Record<string, unknown>[])[0].questions as Record<string, unknown>[])[0].kind = "upload")],
    ["a step without availability", (v: Record<string, unknown>) => delete (v.steps as Record<string, unknown>[])[1].available],
    ["a malformed follow-up rule", (v: Record<string, unknown>) => (((v.steps as Record<string, unknown>[])[2].questions as Record<string, unknown>[])[1].ask_when = { key: 1 })],
    ["an unknown hold reason", (v: Record<string, unknown>) => (((v.intake as Record<string, unknown>).hold as Record<string, unknown>).reason = "guilty")],
    ["an unknown case jurisdiction", (v: Record<string, unknown>) => (((v.intake as Record<string, unknown>).case_jurisdiction as Record<string, unknown>).jurisdiction = "adgm")],
    ["an unknown screening state", (v: Record<string, unknown>) => ((v.intake as Record<string, unknown>).screening = "waived")],
    ["no intake", (v: Record<string, unknown>) => delete v.intake],
    ["an unknown history kind", (v: Record<string, unknown>) => ((v.history as Record<string, unknown>[])[0].kind = "ticket_raised")],
    ["an odd asked key", (v: Record<string, unknown>) => (v.asked = ["Bad Key"])],
    ["a non-string answer label", (v: Record<string, unknown>) => (v.answer_labels = { "incident.history": 1 })],
    ["an unknown screening setting", (v: Record<string, unknown>) => (v.sensitive_screening = "production")],
    ["a malformed escalation", (v: Record<string, unknown>) => ((v.intake as Record<string, unknown>).escalation = { since: 1 })],
    ["a step without sensitivity", (v: Record<string, unknown>) => delete (v.steps as Record<string, unknown>[])[3].sensitive],
  ])("refuses %s", (_, mutate) => {
    const body = apiView();
    mutate(body);
    expect(parseWorkflowView(body)).toBeNull();
  });

  it("isWorkflowView checks the BFF's answer is the same Case", () => {
    expect(isWorkflowView(view(), CASE_ID)).toBe(true);
    expect(isWorkflowView(view(), UUID_A)).toBe(false);
    expect(isWorkflowView({ ...view(), canEdit: "true" }, CASE_ID)).toBe(false);
    expect(isWorkflowView(null, CASE_ID)).toBe(false);
  });
});

describe("parseCaseSummary", () => {
  it("maps and validates a summary", () => {
    expect(parseCaseSummary(apiCaseSummary())).toEqual({
      id: CASE_ID,
      title: "[SYNTHETIC] Attendance concern",
      caseType: "disciplinary",
      workflowKey: "disciplinary",
      status: { code: "case_created", label: "Case created" },
      answered: 0,
      total: 9,
      createdAt: "2026-10-15T09:00:00Z",
      updatedAt: "2026-10-15T09:30:00Z",
    });
    expect(parseCaseSummary(apiCaseSummary({ answered: -1 }))).toBeNull();
    expect(parseCaseSummary(apiCaseSummary({ id: "1" }))).toBeNull();
    expect(parseCaseSummaries([apiCaseSummary(), apiCaseSummary({ status: null })])).toBeNull();
    expect(parseCaseSummaries({})).toBeNull();
    expect(parseCaseSummaries([])).toEqual([]);
  });
});

describe("buildAnswers", () => {
  const step = view().steps[0];
  const today = "2026-10-15";

  it("sends only changed answers, trimmed, and clears emptied ones", () => {
    const saved = { "incident.history": "new", "incident.date": "2026-10-01" };
    const draft = { ...draftFrom(step, saved), "incident.narrative": `  ${NARRATIVE}\n`, "incident.date": "" };
    expect(buildAnswers(step, draft, saved, today)).toEqual({
      answers: { "incident.narrative": NARRATIVE, "incident.date": null },
      errors: {},
    });
    expect(buildAnswers(step, draftFrom(step, saved), saved, today)).toEqual({ answers: {}, errors: {} });
  });

  it("accepts not sure for the date and multi-line text", () => {
    const draft = { ...draftFrom(step, {}), "incident.date": "not_sure", "incident.narrative": "line one\n\tline two" };
    expect(buildAnswers(step, draft, {}, today).errors).toEqual({});
  });

  it.each([
    ["incident.date", "2026-10-16", "The date can't be in the future."],
    ["incident.date", "15/10/2026", "Please enter a valid date."],
    ["incident.date", "1985-01-01", "Please check the year."],
    ["incident.history", "serious", "Please choose one of the options."],
    ["incident.narrative", "x".repeat(4001), "Please keep this to 4,000 characters or fewer."],
  ])("flags %s = %j", (key, value, message) => {
    const result = buildAnswers(step, { ...draftFrom(step, {}), [key]: value }, {}, today);
    expect(result.errors).toEqual({ [key]: message });
    expect(result.answers).toEqual({});
  });

  it("sends a follow-up only while the answer it depends on asks for it", () => {
    const context = view().steps[2];
    const connection = context.questions[1];
    const outside = { ...draftFrom(context, {}), "context.location": "outside_work", "context.work_connection": "yes" };
    expect(isAsked(connection, mergedAnswers(context, outside, {}))).toBe(true);
    expect(buildAnswers(context, outside, {}, today).answers).toEqual({ "context.location": "outside_work", "context.work_connection": "yes" });
    // Changed back to "at work": the follow-up isn't sent, and a saved answer to it isn't cleared.
    const saved = { "context.location": "outside_work", "context.work_connection": "yes" };
    const atWork = { ...draftFrom(context, saved), "context.location": "at_work", "context.work_connection": "" };
    expect(buildAnswers(context, atWork, saved, today).answers).toEqual({ "context.location": "at_work" });
    // A follow-up can depend on another step's saved answer.
    const documented = context.questions[2];
    expect(isAsked(documented, { "incident.history": "raised_before" })).toBe(true);
    expect(isAsked(documented, { "incident.history": "new" })).toBe(false);
  });

  it("sends a whole screening group as given", () => {
    const screening = view({ company: "uae_federal", answers: { "jurisdiction.case_confirmation": "uae_federal" } }).steps[3];
    const draft = { ...draftFrom(screening, {}), ...ALL_CLEAR, "screening.sick_leave": "not_sure" };
    expect(buildAnswers(screening, draft, {}, today).answers).toEqual({ ...ALL_CLEAR, "screening.sick_leave": "not_sure" });
  });
});

describe("copy", () => {
  it("reads answers back as given, never interpreted", () => {
    const [narrative, date, history] = view().steps[0].questions;
    expect(displayAnswer(history, "raised_before")).toBe("It has been raised before");
    expect(displayAnswer(date, "not_sure")).toBe("Not sure");
    expect(displayAnswer(date, "2026-10-01")).toBe("1 Oct 2026");
    expect(displayAnswer(narrative, NARRATIVE)).toBe(NARRATIVE);
  });

  it("formats dates in UTC so server and browser agree", () => {
    expect(formatDay("2026-10-15T23:30:00Z")).toBe("15 Oct 2026");
    expect(formatDayTime("2026-10-15T09:05:00Z")).toBe("15 Oct 2026, 09:05 UTC");
    expect(formatDay("not a date")).toBe("");
  });
});

describe("request parsers (BFF)", () => {
  it("rebuilds a case creation with exactly the API's fields", () => {
    expect(parseCaseCreate({ title: "Attendance", requestKey: UUID_A })).toEqual({
      ok: true,
      value: { title: "Attendance", request_key: UUID_A },
    });
  });

  it.each([
    [{ title: "Attendance", requestKey: UUID_A, caseType: "probation" }],
    [{ title: "Attendance", requestKey: UUID_A, companyId: UUID_A }],
    [{ title: " Attendance", requestKey: UUID_A }],
    [{ title: "", requestKey: UUID_A }],
    [{ title: "x".repeat(201), requestKey: UUID_A }],
    [{ title: "Tab\there", requestKey: UUID_A }],
    [{ title: "Attendance", requestKey: "not-a-uuid" }],
    [{ title: 7, requestKey: UUID_A }],
    [[]],
    [null],
  ])("refuses case creation %j", (body) => {
    expect(parseCaseCreate(body)).toEqual({ ok: false });
  });

  it("rebuilds an answer save and allows clearing", () => {
    expect(
      parseAnswersSave({ expectedRevision: 2, submissionKey: UUID_A, answers: { "incident.history": "new", "incident.date": null } }),
    ).toEqual({
      ok: true,
      value: { expected_revision: 2, submission_key: UUID_A, answers: { "incident.history": "new", "incident.date": null } },
    });
  });

  it.each([
    [{ expectedRevision: -1, submissionKey: UUID_A, answers: {} }],
    [{ expectedRevision: 1.5, submissionKey: UUID_A, answers: {} }],
    [{ expectedRevision: "1", submissionKey: UUID_A, answers: {} }],
    [{ expectedRevision: 1, submissionKey: "x", answers: {} }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: [] }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: { "Bad Key": "x" } }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: { "incident.history": 1 } }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: { "incident.narrative": "x".repeat(4001) } }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: Object.fromEntries(Array.from({ length: 51 }, (_, i) => [`k${i}`, "x"])) }],
    [{ expectedRevision: 1, submissionKey: UUID_A, answers: {}, revision: 9 }],
  ])("refuses answer save %#", (body) => {
    expect(parseAnswersSave(body)).toEqual({ ok: false });
  });
});
