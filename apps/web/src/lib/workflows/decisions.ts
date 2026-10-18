import type { Tone } from "./copy";

/**
 * Employer decision records and the unified case history (M2-04): the shapes
 * and strict parsers for the view's `decisions` and `timeline` blocks and for
 * a history page. Client-safe (no server imports).
 *
 * A decision record is the employer's own account of what it did or decided;
 * HeroOS stores it as entered and verifies none of it. It never authorizes a
 * workflow step: it doesn't start or complete a stage, release a hold or count
 * as a warning. The browser only offers the factual categories this version
 * knows, whatever a payload says, and renders what the API decided.
 */

export const DECISION_CATEGORIES = [
  "internal_review_completed",
  "information_requested",
  "meeting_recorded",
  "employer_observation",
  "internal_pause_or_follow_up",
  "other_note",
] as const;
export type DecisionCategory = (typeof DECISION_CATEGORIES)[number];
export const EVIDENCE_KINDS = ["internal_document", "meeting_note", "policy", "other"] as const;
export type EvidenceKind = (typeof EVIDENCE_KINDS)[number];
export type EvidenceStatus = "held" | "none" | "not_sure";
export type DecisionMaker = "recorder" | "other";
export type Relation = "original" | "correction" | "clarification";

export type Choice = { key: string; label: string; description: string };
export type DecisionLimits = {
  summary: number;
  explanation: number;
  decisionMakerRole: number;
  changeReason: number;
  evidenceItems: number;
  evidenceDescription: number;
  evidenceReference: number;
};
export type DecisionOptions = {
  categories: Choice[];
  decisionMakers: Choice[];
  evidenceStatuses: Choice[];
  evidenceKinds: Choice[];
  limits: DecisionLimits;
  /** What a record is (the employer's account) and isn't (an authorization). */
  notice: string;
  notRecordable: string;
  evidenceNotice: string;
};
export type Evidence = { kind: EvidenceKind; kindLabel: string; description: string; reference: string | null };
export type DecisionRecord = {
  id: string;
  chainId: string;
  version: number;
  relation: Relation;
  supersedes: string | null;
  supersededBy: string | null;
  /** The latest version of its chain: the only one that can be corrected. */
  current: boolean;
  category: string;
  categoryLabel: string;
  summary: string;
  explanation: string;
  /** YYYY-MM-DD, as the employer gave it. */
  occurredOn: string;
  decisionMaker: DecisionMaker;
  /** "other": the role the employer named (unverified). */
  decisionMakerRole: string | null;
  evidenceStatus: EvidenceStatus;
  evidence: Evidence[];
  changeReason: string | null;
  recordedAt: string;
  recordedByViewer: boolean;
};
export type Decisions = {
  options: DecisionOptions;
  /** Newest first, every version. */
  records: DecisionRecord[];
  canRecord: boolean;
  /** On a write response: the record that request saved. */
  saved: string | null;
};

export type TimelineNature = "employer_record" | "system_check" | "refused_request" | "workflow_change";
export type TimelineStatus = "applied" | "refused" | "specialist_review" | "on_hold" | "current" | "superseded";
export type TimelineEntry = {
  /** Stable; the cursor for the next page. */
  id: string;
  at: string;
  category: "case" | "answers" | "intake" | "progression" | "decisions";
  kind: string;
  nature: TimelineNature;
  title: string;
  detail: string | null;
  byViewer: boolean | null;
  status: TimelineStatus | null;
  link: { relation: "correction" | "clarification" | null; supersedes: string | null; supersededBy: string | null } | null;
};
export type TimelinePage = { entries: TimelineEntry[]; nextBefore: string | null; total: number };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** A history entry id (also the API's `before` cursor). */
export const ENTRY_ID = /^[a-z]+(:[a-z0-9_-]+){0,3}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string";
const isOptionalText = (value: unknown): value is string | null => value === null || typeof value === "string";
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isId = (value: unknown): value is string => isText(value) && UUID.test(value);
const isOptionalId = (value: unknown): value is string | null => value === null || isId(value);

function list<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(parse);
  return items.every((item): item is T => item !== null) ? items : null;
}

function parseChoice(value: unknown): Choice | null {
  return isRecord(value) && isText(value.key) && isText(value.label) && isText(value.description)
    ? { key: value.key, label: value.label, description: value.description }
    : null;
}

function parseLimits(value: unknown): DecisionLimits | null {
  if (!isRecord(value)) return null;
  const keys = [
    ["summary", "summary"],
    ["explanation", "explanation"],
    ["decision_maker_role", "decisionMakerRole"],
    ["change_reason", "changeReason"],
    ["evidence_items", "evidenceItems"],
    ["evidence_description", "evidenceDescription"],
    ["evidence_reference", "evidenceReference"],
  ] as const;
  if (!keys.every(([api]) => isCount(value[api]))) return null;
  return Object.fromEntries(keys.map(([api, web]) => [web, value[api]])) as DecisionLimits;
}

export function parseDecisionOptions(value: unknown): DecisionOptions | null {
  if (!isRecord(value)) return null;
  const categories = list(value.categories, parseChoice);
  const decisionMakers = list(value.decision_makers, parseChoice);
  const evidenceStatuses = list(value.evidence_statuses, parseChoice);
  const evidenceKinds = list(value.evidence_kinds, parseChoice);
  const limits = parseLimits(value.limits);
  if (
    categories === null ||
    decisionMakers === null ||
    evidenceStatuses === null ||
    evidenceKinds === null ||
    limits === null ||
    !isText(value.notice) ||
    !isText(value.not_recordable) ||
    !isText(value.evidence_notice)
  ) {
    return null;
  }
  return {
    // Only the factual categories this version knows are ever offered.
    categories: categories.filter((choice) => (DECISION_CATEGORIES as readonly string[]).includes(choice.key)),
    decisionMakers: decisionMakers.filter((choice) => choice.key === "recorder" || choice.key === "other"),
    evidenceStatuses: evidenceStatuses.filter((choice) => ["held", "none", "not_sure"].includes(choice.key)),
    evidenceKinds: evidenceKinds.filter((choice) => (EVIDENCE_KINDS as readonly string[]).includes(choice.key)),
    limits,
    notice: value.notice,
    notRecordable: value.not_recordable,
    evidenceNotice: value.evidence_notice,
  };
}

function parseEvidence(value: unknown): Evidence | null {
  return isRecord(value) &&
    isText(value.kind) &&
    (EVIDENCE_KINDS as readonly string[]).includes(value.kind) &&
    isText(value.kind_label) &&
    isText(value.description) &&
    isOptionalText(value.reference)
    ? { kind: value.kind as EvidenceKind, kindLabel: value.kind_label, description: value.description, reference: value.reference }
    : null;
}

function parseRecord(value: unknown): DecisionRecord | null {
  if (!isRecord(value)) return null;
  const evidence = list(value.evidence, parseEvidence);
  if (
    !isId(value.id) ||
    !isId(value.chain_id) ||
    !isCount(value.version) ||
    !(value.relation === "original" || value.relation === "correction" || value.relation === "clarification") ||
    !isOptionalId(value.supersedes) ||
    !isOptionalId(value.superseded_by) ||
    typeof value.current !== "boolean" ||
    !isText(value.category) ||
    !isText(value.category_label) ||
    !isText(value.summary) ||
    !isText(value.explanation) ||
    !isText(value.occurred_on) ||
    !DAY.test(value.occurred_on) ||
    !(value.decision_maker === "recorder" || value.decision_maker === "other") ||
    !isOptionalText(value.decision_maker_role) ||
    !(value.evidence_status === "held" || value.evidence_status === "none" || value.evidence_status === "not_sure") ||
    evidence === null ||
    !isOptionalText(value.change_reason) ||
    !isText(value.recorded_at) ||
    typeof value.recorded_by_viewer !== "boolean"
  ) {
    return null;
  }
  return {
    id: value.id,
    chainId: value.chain_id,
    version: value.version,
    relation: value.relation,
    supersedes: value.supersedes,
    supersededBy: value.superseded_by,
    // Current exactly when nothing superseded it, whatever the payload says.
    current: value.current && value.superseded_by === null,
    category: value.category,
    categoryLabel: value.category_label,
    summary: value.summary,
    explanation: value.explanation,
    occurredOn: value.occurred_on,
    decisionMaker: value.decision_maker,
    decisionMakerRole: value.decision_maker_role,
    evidenceStatus: value.evidence_status,
    evidence,
    changeReason: value.change_reason,
    recordedAt: value.recorded_at,
    recordedByViewer: value.recorded_by_viewer,
  };
}

/** The view's `decisions` block: null from an API that doesn't send it, undefined if malformed. */
export function parseDecisions(value: unknown): Decisions | null | undefined {
  if (value === undefined) return null;
  if (!isRecord(value) || typeof value.can_record !== "boolean" || !isOptionalId(value.saved)) return undefined;
  const options = parseDecisionOptions(value.options);
  const records = list(value.records, parseRecord);
  if (options === null || records === null) return undefined;
  return { options, records, canRecord: value.can_record, saved: value.saved };
}

const NATURES = new Set<string>(["employer_record", "system_check", "refused_request", "workflow_change"]);
const CATEGORIES = new Set<string>(["case", "answers", "intake", "progression", "decisions"]);
const STATUSES = new Set<string>(["applied", "refused", "specialist_review", "on_hold", "current", "superseded"]);

/** One entry; `undefined` for a nature or category this version doesn't know (skipped). */
function parseEntry(value: unknown): TimelineEntry | null | undefined {
  if (!isRecord(value) || !isText(value.id) || !ENTRY_ID.test(value.id)) return null;
  if (!isText(value.nature) || !NATURES.has(value.nature) || !isText(value.category) || !CATEGORIES.has(value.category)) {
    return undefined;
  }
  const link = value.link;
  const validLink =
    link === null ||
    (isRecord(link) &&
      (link.relation === null || link.relation === "correction" || link.relation === "clarification") &&
      isOptionalText(link.supersedes) &&
      isOptionalText(link.superseded_by));
  if (
    !isText(value.at) ||
    !isText(value.kind) ||
    !isText(value.title) ||
    !isOptionalText(value.detail) ||
    !(value.by_viewer === null || typeof value.by_viewer === "boolean") ||
    !(value.status === null || (isText(value.status) && STATUSES.has(value.status))) ||
    !validLink
  ) {
    return null;
  }
  return {
    id: value.id,
    at: value.at,
    category: value.category as TimelineEntry["category"],
    kind: value.kind,
    nature: value.nature as TimelineNature,
    title: value.title,
    detail: value.detail,
    byViewer: value.by_viewer,
    status: value.status as TimelineStatus | null,
    link: isRecord(link)
      ? {
          relation: link.relation as "correction" | "clarification" | null,
          supersedes: link.supersedes as string | null,
          supersededBy: link.superseded_by as string | null,
        }
      : null,
  };
}

/** A history page (the view's `timeline`, or a page read later); null if malformed. */
export function parseTimelinePage(value: unknown): TimelinePage | null {
  if (!isRecord(value) || !Array.isArray(value.entries) || !isCount(value.total)) return null;
  if (!(value.next_before === null || (isText(value.next_before) && ENTRY_ID.test(value.next_before)))) return null;
  const entries = value.entries.map(parseEntry);
  if (entries.some((entry) => entry === null)) return null;
  return {
    entries: entries.filter((entry): entry is TimelineEntry => entry !== undefined && entry !== null),
    nextBefore: value.next_before,
    total: value.total,
  };
}

/** The view's `timeline`: null from an API that doesn't send it, undefined if malformed. */
export function parseTimeline(value: unknown): TimelinePage | null | undefined {
  if (value === undefined) return null;
  return parseTimelinePage(value) ?? undefined;
}

/** The current version of each chain, newest first, with its earlier versions (newest first). */
export function chains(records: DecisionRecord[]): { current: DecisionRecord; earlier: DecisionRecord[] }[] {
  const byChain = new Map<string, DecisionRecord[]>();
  for (const record of records) byChain.set(record.chainId, [...(byChain.get(record.chainId) ?? []), record]);
  return [...byChain.values()]
    .map((versions) => [...versions].sort((a, b) => b.version - a.version))
    .map(([current, ...earlier]) => ({ current, earlier }))
    .sort((a, b) => (a.current.recordedAt < b.current.recordedAt ? 1 : a.current.recordedAt > b.current.recordedAt ? -1 : 0));
}

// --- copy -------------------------------------------------------------------------------

export const NATURE_COPY: Record<TimelineNature, { label: string; tone: Tone }> = {
  employer_record: { label: "Employer record", tone: "neutral" },
  system_check: { label: "HeroOS check", tone: "muted" },
  refused_request: { label: "Not allowed: nothing changed", tone: "caution" },
  workflow_change: { label: "Workflow step", tone: "positive" },
};

export const STATUS_COPY: Record<TimelineStatus, { label: string; tone: Tone }> = {
  applied: { label: "Recorded", tone: "positive" },
  refused: { label: "Refused", tone: "caution" },
  specialist_review: { label: "Specialist review needed", tone: "caution" },
  on_hold: { label: "On hold", tone: "caution" },
  current: { label: "Current", tone: "positive" },
  superseded: { label: "Replaced", tone: "muted" },
};

export const RELATION_COPY: Record<Relation, string> = {
  original: "First record",
  correction: "Corrected",
  clarification: "Clarified",
};

/** How a record names who is responsible (never a verified identity). */
export function responsibleText(record: DecisionRecord): string {
  if (record.decisionMaker === "other") return `${record.decisionMakerRole ?? "Someone else"} (as stated by your company)`;
  return record.recordedByViewer ? "You, the person who recorded it" : "The administrator who recorded it";
}

/** A history page as the BFF returns it, in the browser (shape only; the server parsed it). */
export function isTimelinePage(value: unknown): value is TimelinePage {
  return (
    isRecord(value) &&
    Array.isArray(value.entries) &&
    value.entries.every((entry) => isRecord(entry) && isText(entry.id) && isText(entry.title) && isText(entry.at) && isText(entry.nature)) &&
    (value.nextBefore === null || isText(value.nextBefore)) &&
    isCount(value.total)
  );
}
