import { DECISION_CATEGORIES, type DecisionCategory, EVIDENCE_KINDS, type EvidenceKind } from "./decisions";
import { FACT_KEY, KEY, TITLE_MAX, UUID } from "./model";
import { CODE } from "./progression";

/**
 * Browser → BFF request bodies for workflow Cases, re-validated on the web
 * server and rebuilt field by field (unknown keys refused) before they reach
 * the HeroOS API. The API validates again and decides; these checks only keep
 * malformed or oversized requests away from it.
 */

export type ParsedRequest<T> = { ok: true; value: T } | { ok: false };

/** More than any step asks for; a bound on the request, not a product rule. */
export const MAX_ANSWERS = 50;
/** Free-text answers are limited to 4,000 characters by the API. */
export const MAX_ANSWER_LENGTH = 4000;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const onlyKeys = (value: Json, keys: string[]) => Object.keys(value).every((key) => keys.includes(key));
const CONTROL = /[\u0000-\u001f\u007f]/;

export function parseCaseCreate(body: unknown): ParsedRequest<{ title: string; request_key: string }> {
  if (!isRecord(body) || !onlyKeys(body, ["title", "requestKey"])) return { ok: false };
  const { title, requestKey } = body;
  if (
    typeof title !== "string" ||
    title.length === 0 ||
    title.length > TITLE_MAX ||
    title !== title.trim() ||
    CONTROL.test(title) ||
    typeof requestKey !== "string" ||
    !UUID.test(requestKey)
  ) {
    return { ok: false };
  }
  return { ok: true, value: { title, request_key: requestKey } };
}

/** Line breaks and tabs are the only control characters free text may hold (as the API checks). */
const TEXT_CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;

/**
 * Ask HeroOS (`POST /bff/companies/{id}/ask`): the founder's words, the
 * neutral title of the case they open, and one key per write so a retry after
 * a lost response is applied once. The text is checked as the API checks a
 * free-text answer: not empty, no surrounding whitespace, at most 4,000
 * characters, no control characters but line breaks and tabs.
 */
export function parseAskStart(
  body: unknown,
): ParsedRequest<{ text: string; title: string; requestKey: string; submissionKey: string }> {
  if (!isRecord(body) || !onlyKeys(body, ["text", "title", "requestKey", "submissionKey"])) return { ok: false };
  const { text, title, requestKey, submissionKey } = body;
  if (
    typeof text !== "string" ||
    text.length === 0 ||
    text.length > MAX_ANSWER_LENGTH ||
    text !== text.trim() ||
    TEXT_CONTROL.test(text) ||
    typeof title !== "string" ||
    title.length === 0 ||
    title.length > TITLE_MAX ||
    title !== title.trim() ||
    CONTROL.test(title) ||
    typeof requestKey !== "string" ||
    !UUID.test(requestKey) ||
    typeof submissionKey !== "string" ||
    !UUID.test(submissionKey) ||
    requestKey === submissionKey
  ) {
    return { ok: false };
  }
  return { ok: true, value: { text, title, requestKey, submissionKey } };
}

export function parseAnswersSave(body: unknown): ParsedRequest<{
  expected_revision: number;
  submission_key: string;
  answers: Record<string, string | null>;
}> {
  if (!isRecord(body) || !onlyKeys(body, ["expectedRevision", "submissionKey", "answers"])) return { ok: false };
  const { expectedRevision, submissionKey, answers } = body;
  if (
    typeof expectedRevision !== "number" ||
    !Number.isInteger(expectedRevision) ||
    expectedRevision < 0 ||
    typeof submissionKey !== "string" ||
    !UUID.test(submissionKey) ||
    !isRecord(answers)
  ) {
    return { ok: false };
  }
  const entries = Object.entries(answers);
  if (
    entries.length > MAX_ANSWERS ||
    !entries.every(
      ([key, value]) =>
        FACT_KEY.test(key) && (value === null || (typeof value === "string" && value.length <= MAX_ANSWER_LENGTH)),
    )
  ) {
    return { ok: false };
  }
  return {
    ok: true,
    value: {
      expected_revision: expectedRevision,
      submission_key: submissionKey,
      answers: Object.fromEntries(entries) as Record<string, string | null>,
    },
  };
}

/** More warnings than any transition raises; a bound on the request, not a product rule. */
export const MAX_ACKNOWLEDGED = 40;
const STAGE_TRANSITION = /^(start|complete):[a-z][a-z_]{0,49}$/;

function acknowledged(value: unknown): string[] | null {
  if (value === undefined) return [];
  return Array.isArray(value) &&
    value.length <= MAX_ACKNOWLEDGED &&
    value.every((code) => typeof code === "string" && CODE.test(code)) &&
    new Set(value).size === value.length
    ? (value as string[])
    : null;
}

type ProgressionBase = { expected_revision: number; request_key: string; acknowledged_warnings: string[] };

function progressionBase(body: Json, extra: string): ParsedRequest<ProgressionBase> {
  if (!onlyKeys(body, ["expectedRevision", "requestKey", "acknowledgedWarnings", extra])) return { ok: false };
  const { expectedRevision, requestKey } = body;
  const warnings = acknowledged(body.acknowledgedWarnings);
  if (
    typeof expectedRevision !== "number" ||
    !Number.isInteger(expectedRevision) ||
    expectedRevision < 0 ||
    typeof requestKey !== "string" ||
    !UUID.test(requestKey) ||
    warnings === null
  ) {
    return { ok: false };
  }
  return { ok: true, value: { expected_revision: expectedRevision, request_key: requestKey, acknowledged_warnings: warnings } };
}

/** The employer's pathway choice (M2-03). The API decides whether it is recorded. */
export function parsePathwayRequest(body: unknown): ParsedRequest<ProgressionBase & { pathway: string }> {
  if (!isRecord(body)) return { ok: false };
  const base = progressionBase(body, "pathway");
  const { pathway } = body;
  if (!base.ok || typeof pathway !== "string" || !KEY.test(pathway) || pathway.length > 30) return { ok: false };
  return { ok: true, value: { ...base.value, pathway } };
}

/** A requested stage transition (M2-03): a key the API offered. The API decides. */
export function parseTransitionRequest(body: unknown): ParsedRequest<ProgressionBase & { transition: string }> {
  if (!isRecord(body)) return { ok: false };
  const base = progressionBase(body, "transition");
  const { transition } = body;
  if (!base.ok || typeof transition !== "string" || !STAGE_TRANSITION.test(transition)) return { ok: false };
  return { ok: true, value: { ...base.value, transition } };
}

// --- employer decision records (M2-04) -------------------------------------------------

/** The API's bounds (characters, counts); the API checks them again. */
export const DECISION_LIMITS = {
  summary: 200,
  explanation: 4000,
  decisionMakerRole: 120,
  changeReason: 500,
  evidenceItems: 10,
  evidenceDescription: 300,
  evidenceReference: 200,
} as const;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MULTI_LINE_CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;

type EvidencePayload = { kind: EvidenceKind; description: string; reference: string | null };
export type DecisionPayload = {
  expected_revision: number;
  request_key: string;
  category: DecisionCategory;
  summary: string;
  explanation: string;
  occurred_on: string;
  decision_maker: "recorder" | "other";
  decision_maker_role: string | null;
  evidence_status: "held" | "none" | "not_sure";
  evidence: EvidencePayload[];
};
export type CorrectionPayload = DecisionPayload & { relation: "correction" | "clarification"; change_reason: string };

const singleLine = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= max && value === value.trim() && !CONTROL.test(value);
const multiLine = (value: unknown, max: number): value is string =>
  typeof value === "string" &&
  value.trim().length > 0 &&
  value.length <= max &&
  value === value.trim() &&
  !MULTI_LINE_CONTROL.test(value);

function evidenceItems(value: unknown): EvidencePayload[] | null {
  if (!Array.isArray(value) || value.length > DECISION_LIMITS.evidenceItems) return null;
  const items = value.map((item): EvidencePayload | null => {
    if (!isRecord(item) || !onlyKeys(item, ["kind", "description", "reference"])) return null;
    const { kind, description, reference } = item;
    if (
      typeof kind !== "string" ||
      !(EVIDENCE_KINDS as readonly string[]).includes(kind) ||
      !singleLine(description, DECISION_LIMITS.evidenceDescription) ||
      !(reference === undefined || reference === null || singleLine(reference, DECISION_LIMITS.evidenceReference))
    ) {
      return null;
    }
    return { kind: kind as EvidenceKind, description, reference: reference ?? null };
  });
  return items.every((item): item is EvidencePayload => item !== null) ? items : null;
}

const DECISION_FIELDS = [
  "expectedRevision",
  "requestKey",
  "category",
  "summary",
  "explanation",
  "occurredOn",
  "decisionMaker",
  "decisionMakerRole",
  "evidenceStatus",
  "evidence",
];

function decision(body: Json): DecisionPayload | null {
  const { expectedRevision, requestKey, category, summary, explanation, occurredOn, decisionMaker, decisionMakerRole, evidenceStatus } =
    body;
  const evidence = evidenceItems(body.evidence ?? []);
  const role = decisionMakerRole ?? null;
  if (
    typeof expectedRevision !== "number" ||
    !Number.isInteger(expectedRevision) ||
    expectedRevision < 0 ||
    typeof requestKey !== "string" ||
    !UUID.test(requestKey) ||
    typeof category !== "string" ||
    // Only factual categories: nothing here can stand for a warning or an outcome.
    !(DECISION_CATEGORIES as readonly string[]).includes(category) ||
    !singleLine(summary, DECISION_LIMITS.summary) ||
    !multiLine(explanation, DECISION_LIMITS.explanation) ||
    typeof occurredOn !== "string" ||
    !DAY.test(occurredOn) ||
    !(decisionMaker === "recorder" || decisionMaker === "other") ||
    !(role === null || singleLine(role, DECISION_LIMITS.decisionMakerRole)) ||
    (decisionMaker === "other") !== (role !== null) ||
    !(evidenceStatus === "held" || evidenceStatus === "none" || evidenceStatus === "not_sure") ||
    evidence === null ||
    (evidenceStatus === "held") !== evidence.length > 0
  ) {
    return null;
  }
  return {
    expected_revision: expectedRevision,
    request_key: requestKey,
    category: category as DecisionCategory,
    summary,
    explanation,
    occurred_on: occurredOn,
    decision_maker: decisionMaker,
    decision_maker_role: role,
    evidence_status: evidenceStatus,
    evidence,
  };
}

/** A new employer decision record (M2-04). The API decides; the actor is the session's. */
export function parseDecisionRequest(body: unknown): ParsedRequest<DecisionPayload> {
  if (!isRecord(body) || !onlyKeys(body, DECISION_FIELDS)) return { ok: false };
  const value = decision(body);
  return value === null ? { ok: false } : { ok: true, value };
}

/** A correction or clarification of an earlier record (a new version; nothing is erased). */
export function parseCorrectionRequest(body: unknown): ParsedRequest<CorrectionPayload> {
  if (!isRecord(body) || !onlyKeys(body, [...DECISION_FIELDS, "relation", "changeReason"])) return { ok: false };
  const value = decision(body);
  const { relation, changeReason } = body;
  if (
    value === null ||
    !(relation === "correction" || relation === "clarification") ||
    !multiLine(changeReason, DECISION_LIMITS.changeReason)
  ) {
    return { ok: false };
  }
  return { ok: true, value: { ...value, relation, change_reason: changeReason } };
}
