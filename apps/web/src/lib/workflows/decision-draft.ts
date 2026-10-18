import type { DecisionLimits, DecisionRecord, EvidenceKind, EvidenceStatus } from "./decisions";

/**
 * The decision-record form's draft (M2-04): what the administrator typed, the
 * checks the browser can make before sending (the API checks everything again
 * and decides), and the request body for the BFF. Text is trimmed, never
 * otherwise rewritten. Client-safe and pure.
 */

export type EvidenceDraft = { kind: EvidenceKind | ""; description: string; reference: string };
export type DecisionDraft = {
  category: string;
  summary: string;
  explanation: string;
  /** YYYY-MM-DD from the date input. */
  occurredOn: string;
  decisionMaker: "recorder" | "other" | "";
  decisionMakerRole: string;
  evidenceStatus: EvidenceStatus | "";
  evidence: EvidenceDraft[];
  /** Corrections and clarifications only: why the earlier version changes. */
  changeReason: string;
};
export type DraftField =
  | "category"
  | "summary"
  | "explanation"
  | "occurredOn"
  | "decisionMaker"
  | "decisionMakerRole"
  | "evidenceStatus"
  | "evidence"
  | "changeReason";
export type DraftErrors = Partial<Record<DraftField, string>>;

/** The API's 422 field names, as form fields. */
export const API_FIELDS: Record<string, DraftField> = {
  category: "category",
  summary: "summary",
  explanation: "explanation",
  occurred_on: "occurredOn",
  decision_maker: "decisionMaker",
  decision_maker_role: "decisionMakerRole",
  evidence_status: "evidenceStatus",
  evidence: "evidence",
  change_reason: "changeReason",
  relation: "changeReason",
};

export const EMPTY_EVIDENCE: EvidenceDraft = { kind: "", description: "", reference: "" };

export function emptyDraft(): DecisionDraft {
  return {
    category: "",
    summary: "",
    explanation: "",
    occurredOn: "",
    decisionMaker: "",
    decisionMakerRole: "",
    evidenceStatus: "",
    evidence: [],
    changeReason: "",
  };
}

/** A correction or clarification starts from the version it replaces. */
export function draftFromRecord(record: DecisionRecord): DecisionDraft {
  return {
    category: record.category,
    summary: record.summary,
    explanation: record.explanation,
    occurredOn: record.occurredOn,
    decisionMaker: record.decisionMaker,
    decisionMakerRole: record.decisionMakerRole ?? "",
    evidenceStatus: record.evidenceStatus,
    evidence: record.evidence.map((item) => ({ kind: item.kind, description: item.description, reference: item.reference ?? "" })),
    changeReason: "",
  };
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
// The API refuses links in evidence (HeroOS stores and opens none); said here first.
const LINK = /:\/\/|(?:^|[^a-z0-9])www\.|^\s*(?:javascript|vbscript|data):\S/i;
const plural = (count: number) => count.toLocaleString("en-GB");

function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** The latest date the API accepts (one day ahead of UTC, for time zones east of it). */
export function latestEventDay(todayUtc: string): string {
  return addDays(todayUtc, 1);
}

export function checkDraft(
  draft: DecisionDraft,
  limits: DecisionLimits,
  { correcting, todayUtc }: { correcting: boolean; todayUtc: string },
): DraftErrors {
  const errors: DraftErrors = {};
  const summary = draft.summary.trim();
  const explanation = draft.explanation.trim();
  const role = draft.decisionMakerRole.trim();
  if (draft.category === "") errors.category = "Choose what you're recording.";
  if (summary === "") errors.summary = "Write a short summary.";
  else if (summary.length > limits.summary) errors.summary = `Keep the summary to ${plural(limits.summary)} characters or fewer.`;
  if (explanation === "") errors.explanation = "Explain what happened or what was decided.";
  else if (explanation.length > limits.explanation) {
    errors.explanation = `Keep the explanation to ${plural(limits.explanation)} characters or fewer.`;
  }
  if (!DAY.test(draft.occurredOn)) errors.occurredOn = "Enter the date it happened.";
  else if (draft.occurredOn > latestEventDay(todayUtc)) errors.occurredOn = "The date can't be in the future.";
  else if (draft.occurredOn < "1990-01-01") errors.occurredOn = "Check the year: the date is too far in the past.";
  if (draft.decisionMaker === "") errors.decisionMaker = "Say who is responsible.";
  else if (draft.decisionMaker === "other" && role === "") errors.decisionMakerRole = "Give their role or job title.";
  else if (role.length > limits.decisionMakerRole) {
    errors.decisionMakerRole = `Keep the role to ${plural(limits.decisionMakerRole)} characters or fewer.`;
  }
  if (draft.evidenceStatus === "") errors.evidenceStatus = "Say whether supporting evidence exists.";
  else if (draft.evidenceStatus === "held") {
    const items = draft.evidence;
    if (items.length === 0) errors.evidence = "Describe at least one item of evidence.";
    else if (items.length > limits.evidenceItems) errors.evidence = `List at most ${plural(limits.evidenceItems)} items.`;
    else if (items.some((item) => item.kind === "" || item.description.trim() === "")) {
      errors.evidence = "Choose a type and describe each item.";
    } else if (
      items.some(
        (item) =>
          item.description.trim().length > limits.evidenceDescription || item.reference.trim().length > limits.evidenceReference,
      )
    ) {
      errors.evidence = `Keep each description to ${plural(limits.evidenceDescription)} characters and each reference to ${plural(limits.evidenceReference)}.`;
    } else if (items.some((item) => LINK.test(item.description) || LINK.test(item.reference))) {
      errors.evidence = "Describe the evidence or give a reference number instead of a link.";
    }
  }
  if (correcting) {
    const reason = draft.changeReason.trim();
    if (reason === "") errors.changeReason = "Say why you're making this change.";
    else if (reason.length > limits.changeReason) {
      errors.changeReason = `Keep the reason to ${plural(limits.changeReason)} characters or fewer.`;
    }
  }
  return errors;
}

/** The BFF request body (camelCase; rebuilt and checked again on the web server). */
export function requestBody(
  draft: DecisionDraft,
  {
    expectedRevision,
    requestKey,
    relation,
  }: { expectedRevision: number; requestKey: string; relation: "correction" | "clarification" | null },
): Record<string, unknown> {
  const held = draft.evidenceStatus === "held";
  const body: Record<string, unknown> = {
    expectedRevision,
    requestKey,
    category: draft.category,
    summary: draft.summary.trim(),
    explanation: draft.explanation.trim(),
    occurredOn: draft.occurredOn,
    decisionMaker: draft.decisionMaker,
    decisionMakerRole: draft.decisionMaker === "other" ? draft.decisionMakerRole.trim() : null,
    evidenceStatus: draft.evidenceStatus,
    evidence: held
      ? draft.evidence.map((item) => ({
          kind: item.kind,
          description: item.description.trim(),
          reference: item.reference.trim() === "" ? null : item.reference.trim(),
        }))
      : [],
  };
  if (relation !== null) {
    body.relation = relation;
    body.changeReason = draft.changeReason.trim();
  }
  return body;
}
