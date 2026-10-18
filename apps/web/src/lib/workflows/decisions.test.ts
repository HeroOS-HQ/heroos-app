import { describe, expect, it } from "vitest";

import { apiDecisions, apiEntry, apiRecord, apiTimeline, apiView, CORRECTION_ID, RECORD_ID } from "@/test/workflow-fixtures";

import { checkDraft, draftFromRecord, emptyDraft, latestEventDay, requestBody } from "./decision-draft";
import { chains, parseDecisions, parseTimeline, parseTimelinePage, responsibleText } from "./decisions";
import { parseWorkflowView } from "./model";
import { parseCorrectionRequest, parseDecisionRequest } from "./requests";

const KEY = "a1b2c3d4-0000-4000-8000-0000000000aa";
const LIMITS = parseDecisions(apiDecisions())!.options.limits;
const REQUEST = {
  expectedRevision: 5,
  requestKey: KEY,
  category: "meeting_recorded",
  summary: "[SYNTHETIC] Check-in meeting held",
  explanation: "[SYNTHETIC] Line one.\nLine two.",
  occurredOn: "2026-10-12",
  decisionMaker: "other",
  decisionMakerRole: "[SYNTHETIC] Shift supervisor",
  evidenceStatus: "held",
  evidence: [{ kind: "meeting_note", description: "[SYNTHETIC] Notes", reference: "HR-2026-014" }],
};

describe("parsing the decisions block and the history", () => {
  it("reads records and keeps an older API working", () => {
    const parsed = parseDecisions(apiDecisions([apiRecord()]))!;
    expect(parsed.records[0]).toMatchObject({ id: RECORD_ID, current: true, decisionMaker: "other", occurredOn: "2026-10-12" });
    expect(parsed.records[0].evidence[0]).toEqual({
      kind: "meeting_note",
      kindLabel: "Meeting note",
      description: "[SYNTHETIC] Meeting notes",
      reference: "HR-2026-014",
    });
    // An API before M2-04 sends neither block: the view still parses.
    const view = parseWorkflowView(apiView({}))!;
    expect(view.decisions).toBeNull();
    expect(view.timeline).toBeNull();
  });

  it("rejects malformed blocks, and with them the view", () => {
    expect(parseDecisions({ ...apiDecisions(), can_record: "yes" })).toBeUndefined();
    expect(parseDecisions(apiDecisions([apiRecord({ occurred_on: "12/10/2026" })]))).toBeUndefined();
    expect(parseDecisions(apiDecisions([apiRecord({ supersedes: "not-a-uuid" })]))).toBeUndefined();
    expect(parseWorkflowView(apiView({ decisions: { records: [] } }))).toBeNull();
    expect(parseTimeline({ entries: [apiEntry("Not An Id")], next_before: null, total: 1 })).toBeUndefined();
    expect(parseTimelinePage({ entries: [], next_before: "x y", total: 0 })).toBeNull();
  });

  it("never treats a superseded record as current, whatever the payload says", () => {
    const parsed = parseDecisions(apiDecisions([apiRecord({ current: true, superseded_by: CORRECTION_ID })]))!;
    expect(parsed.records[0].current).toBe(false);
  });

  it("skips history entries of a kind this version doesn't know", () => {
    const page = parseTimeline(
      apiTimeline([apiEntry("created"), apiEntry("document:abc", { nature: "document_generated", category: "documents" })]),
    )!;
    expect(page.entries.map((entry) => entry.id)).toEqual(["created"]);
  });

  it("groups versions into chains with the current version first", () => {
    const records = parseDecisions(
      apiDecisions([
        apiRecord({ id: CORRECTION_ID, version: 2, relation: "correction", supersedes: RECORD_ID, recorded_at: "2026-10-17T10:00:00Z" }),
        apiRecord({ current: false, superseded_by: CORRECTION_ID }),
      ]),
    )!.records;
    const [chain] = chains(records);
    expect(chain.current.id).toBe(CORRECTION_ID);
    expect(chain.earlier.map((record) => record.id)).toEqual([RECORD_ID]);
    expect(responsibleText(chain.current)).toBe("[SYNTHETIC] Shift supervisor (as stated by your company)");
    expect(responsibleText({ ...chain.current, decisionMaker: "recorder", decisionMakerRole: null })).toBe(
      "You, the person who recorded it",
    );
  });
});

describe("rebuilding decision requests on the web server", () => {
  it("rebuilds a record field by field", () => {
    expect(parseDecisionRequest(REQUEST)).toEqual({
      ok: true,
      value: {
        expected_revision: 5,
        request_key: KEY,
        category: "meeting_recorded",
        summary: "[SYNTHETIC] Check-in meeting held",
        explanation: "[SYNTHETIC] Line one.\nLine two.",
        occurred_on: "2026-10-12",
        decision_maker: "other",
        decision_maker_role: "[SYNTHETIC] Shift supervisor",
        evidence_status: "held",
        evidence: [{ kind: "meeting_note", description: "[SYNTHETIC] Notes", reference: "HR-2026-014" }],
      },
    });
  });

  it.each([
    ["an unsafe category", { category: "formal_warning_issued" }],
    ["a forged actor", { recordedBy: KEY }],
    ["an approval flag", { legalApproval: true }],
    ["a stage key", { transition: "complete:test_check_in" }],
    ["a summary on two lines", { summary: "a\nb" }],
    ["an over-long summary", { summary: "x".repeat(201) }],
    ["a control character", { explanation: "a\u0007b" }],
    ["a timestamp", { occurredOn: "2026-10-12T00:00:00Z" }],
    ["a role without someone else", { decisionMaker: "recorder" }],
    ["someone else without a role", { decisionMakerRole: null }],
    ["held evidence without items", { evidence: [] }],
    ["items without held evidence", { evidenceStatus: "none" }],
    ["an unknown evidence kind", { evidence: [{ kind: "upload", description: "x" }] }],
    ["an extra evidence field", { evidence: [{ kind: "policy", description: "x", url: "x" }] }],
    ["too many items", { evidence: Array.from({ length: 11 }, () => ({ kind: "policy", description: "x" })) }],
    ["a negative revision", { expectedRevision: -1 }],
  ])("refuses %s", (_, change) => {
    expect(parseDecisionRequest({ ...REQUEST, ...change })).toEqual({ ok: false });
  });

  it("accepts a correction only with a relation and a reason", () => {
    expect(parseCorrectionRequest({ ...REQUEST, relation: "correction", changeReason: "[SYNTHETIC] Wrong date." })).toMatchObject({
      ok: true,
      value: { relation: "correction", change_reason: "[SYNTHETIC] Wrong date." },
    });
    expect(parseCorrectionRequest({ ...REQUEST, relation: "approval", changeReason: "x" })).toEqual({ ok: false });
    expect(parseCorrectionRequest({ ...REQUEST, relation: "clarification" })).toEqual({ ok: false });
    // A new record can't smuggle a correction's fields.
    expect(parseDecisionRequest({ ...REQUEST, relation: "correction", changeReason: "x" })).toEqual({ ok: false });
  });
});

describe("the form draft", () => {
  it("starts empty, or from the version it replaces", () => {
    expect(checkDraft(emptyDraft(), LIMITS, { correcting: false, todayUtc: "2026-10-18" })).toMatchObject({
      category: expect.any(String),
      summary: expect.any(String),
      occurredOn: expect.any(String),
      decisionMaker: expect.any(String),
      explanation: expect.any(String),
      evidenceStatus: expect.any(String),
    });
    const record = parseDecisions(apiDecisions([apiRecord()]))!.records[0];
    const draft = draftFromRecord(record);
    expect(checkDraft(draft, LIMITS, { correcting: false, todayUtc: "2026-10-18" })).toEqual({});
    expect(checkDraft(draft, LIMITS, { correcting: true, todayUtc: "2026-10-18" })).toEqual({
      changeReason: "Say why you're making this change.",
    });
  });

  it("names someone in the company as responsible, never HeroOS", () => {
    const draft = draftFromRecord(parseDecisions(apiDecisions([apiRecord()]))!.records[0]);
    const check = (role: string) => checkDraft({ ...draft, decisionMakerRole: role }, LIMITS, { correcting: false, todayUtc: "2026-10-18" });
    expect(check("HeroOS specialist").decisionMakerRole).toBe("Give a role in your company. HeroOS doesn't make decisions.");
    expect(check("Hero OS reviewer").decisionMakerRole).toBeDefined();
    expect(check("Hero Oscar, line manager")).toEqual({});
  });

  it("allows tomorrow (UTC) for time zones ahead, but not later", () => {
    const record = parseDecisions(apiDecisions([apiRecord()]))!.records[0];
    const base = draftFromRecord(record);
    expect(latestEventDay("2026-12-31")).toBe("2027-01-01");
    expect(checkDraft({ ...base, occurredOn: "2026-10-19" }, LIMITS, { correcting: false, todayUtc: "2026-10-18" })).toEqual({});
    expect(checkDraft({ ...base, occurredOn: "2026-10-20" }, LIMITS, { correcting: false, todayUtc: "2026-10-18" }).occurredOn).toBe(
      "The date can't be in the future.",
    );
  });

  it("refuses links as evidence and trims what it sends", () => {
    const record = parseDecisions(apiDecisions([apiRecord()]))!.records[0];
    const draft = draftFromRecord(record);
    for (const link of [
      "https://x.invalid/a",
      "see www.x.invalid",
      "javascript:alert(1)",
      "file:/srv/notes",
      "mailto:hr@x.invalid",
      // Full-width look-alikes fold (NFKC) to a link, as the API checks them.
      "\uff48\uff54\uff54\uff50\uff53\uff1a\uff0f\uff0fx.invalid",
    ]) {
      const errors = checkDraft({ ...draft, evidence: [{ kind: "policy", description: link, reference: "" }] }, LIMITS, {
        correcting: false,
        todayUtc: "2026-10-18",
      });
      expect(errors.evidence).toMatch(/instead of a link/);
    }
    for (const claim of ["HeroOS verified document", "HEROOS-DOC-0001", "\uff28\uff45\uff52\uff4f\uff2f\uff33 export"]) {
      const errors = checkDraft({ ...draft, evidence: [{ kind: "policy", description: "x", reference: claim }] }, LIMITS, {
        correcting: false,
        todayUtc: "2026-10-18",
      });
      expect(errors.evidence).toBe("Describe your company's own evidence. It can't be a HeroOS document.");
    }
    expect(
      checkDraft({ ...draft, evidence: [{ kind: "policy", description: "File: HR-2026-014", reference: "Hero Oscar" }] }, LIMITS, {
        correcting: false,
        todayUtc: "2026-10-18",
      }).evidence,
    ).toBeUndefined();
    const body = requestBody(
      { ...draft, summary: "  padded  ", evidence: [{ kind: "policy", description: " x ", reference: " " }] },
      { expectedRevision: 5, requestKey: KEY, relation: null },
    );
    expect(body.summary).toBe("padded");
    expect(body.evidence).toEqual([{ kind: "policy", description: "x", reference: null }]);
    expect(Object.keys(body)).not.toContain("relation");
    const none = requestBody({ ...draft, evidenceStatus: "none", decisionMaker: "recorder" }, {
      expectedRevision: 5,
      requestKey: KEY,
      relation: "clarification",
    });
    expect(none).toMatchObject({ evidence: [], decisionMakerRole: null, relation: "clarification", changeReason: "" });
  });
});
