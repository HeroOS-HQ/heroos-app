// @vitest-environment node
import { describe, expect, it } from "vitest";

import { apiCaseSummary, apiView, CASE_ID, NARRATIVE, view } from "@/test/workflow-fixtures";

import { buildAnswers, draftFrom } from "./answers";
import { displayAnswer, formatDay, formatDayTime } from "./copy";
import { isWorkflowView, parseCaseSummaries, parseCaseSummary, parseWorkflowView } from "./model";
import { parseAnswersSave, parseCaseCreate } from "./requests";

const UUID_A = "a1b2c3d4-0000-4000-8000-000000000001";

describe("parseWorkflowView", () => {
  it("maps the API's view to the web shape", () => {
    const parsed = parseWorkflowView(apiView({ answers: { "incident.history": "new" }, revision: 3 }));
    expect(parsed).not.toBeNull();
    expect(parsed!.case.id).toBe(CASE_ID);
    expect(parsed!.workflow).toEqual({ key: "disciplinary", title: "Disciplinary", definitionVersion: 1, revision: 3 });
    expect(parsed!.answers).toEqual({ "incident.history": "new" });
    expect(parsed!.steps[0].questions.map((q) => q.kind)).toEqual(["text", "date", "choice", "choice", "choice"]);
    expect(parsed!.steps[0].questions[1].allowNotSure).toBe(true);
    expect(parsed!.conversation.map((m) => m.kind)).toEqual([
      "information",
      "question_group",
      "answer_confirmation",
      "status_notice",
      "missing_information",
      "status_notice",
      "status_notice",
    ]);
  });

  it("allows guidance only for a supported, confirmed jurisdiction", () => {
    const tampered = apiView();
    (tampered.jurisdiction as Record<string, unknown>).guidance_allowed = true;
    expect(parseWorkflowView(tampered)!.jurisdiction.guidanceAllowed).toBe(false);
    expect(parseWorkflowView(apiView({ readiness: "supported_confirmed" }))!.jurisdiction.guidanceAllowed).toBe(true);
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
      total: 5,
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
