import { MAX_MESSAGE_CHARS } from "@/lib/assistant/model";

/**
 * Ask HeroOS's persistent conversations (M2-NEW-05, stored since M2-NEW-07):
 * shapes, limits and field-by-field validation for the gateway
 * (`/bff/companies/{id}/assistant/...`). The founder writes in their own
 * words; there is no Case, workflow, category or stage to choose.
 *
 * The browser is thin. A message sends only the founder's words, a turn key
 * (one per send attempt; a retry reuses it), the conversation id (none for a
 * new one) and the revision it last saw. The server holds everything that
 * decides anything: the conversation, its Case and facts, the checks. The
 * `outcome` (Guidance, Warning, Block, Expert Review, or checks unavailable)
 * is the API's deterministic result in its own words (M2-NEW-06), shown as
 * given; a message's author is relative to the viewer ("you", "another
 * administrator", HeroOS). The status keeps its dimensions apart: an action's
 * Expert Review never pauses the Case, and checks that can't run are never an
 * HR outcome.
 *
 * Every API answer is rebuilt field by field (unknown keys refused); the BFF
 * passes on exactly these shapes, and the browser checks them again. The limits
 * match the API (app/api/gateway.py), which checks them again.
 */

export { MAX_MESSAGE_CHARS };
export const MAX_REVISION = 10_000;
// The conversation list's cursor (activity time in microseconds, and the id).
export const CONVERSATION_CURSOR = /^[0-9]{1,20}\.[0-9a-f]{32}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const WORKFLOW_KEY = /^[a-z][a-z_]{0,49}$/;
const MAX_TITLE = 200;
const MAX_TEXT = 8000;
const MAX_ITEMS = 100;
const MAX_REVIEW_ACTIONS = 12;

export type GatewayUnavailable = "disabled" | "not_configured" | "knowledge_unavailable";
export type GatewayStatus = { available: boolean; reason: GatewayUnavailable | null; notice: string | null };

export type ConversationState = "responded" | "clarifying" | "outside_approved_guidance";
/** The deterministic outcome HeroOS's checks decided; "unavailable" is technical, never an HR outcome. */
export type OutcomeKind = "guidance" | "warning" | "block" | "expert_review" | "unavailable";
export type StepKind = Exclude<OutcomeKind, "unavailable">;
export type Outcome = { kind: OutcomeKind; title: string; message: string; items: { kind: StepKind; text: string }[] };

export type Author = "you" | "another_administrator" | "heroos";
export type ConversationMessage = {
  sequence: number;
  author: Author;
  text: string;
  safeNextStep: string | null;
  conversationState: ConversationState | null;
  outcome: Outcome | null;
  createdAt: string;
};
export type CaseLink = { id: string; title: string };
/** The Case's formal workflow position (M2-NEW-08): what its employer recorded, in words. */
export type CasePosition = {
  state: string;
  label: string;
  /** The recorded pathway: the employer's decision. */
  pathway: string | null;
  /** The stage in progress, else the next one that can start. */
  stage: string | null;
  stageInProgress: boolean;
  /** Case steps the progression rules hold for specialist review (never the whole Case). */
  heldSteps: string[];
};
export type ConversationStatus = {
  lifecycle: "in_progress" | "paused" | null;
  workflow: { key: string; title: string | null } | null;
  attention: {
    needsInformation: boolean;
    /** Jurisdiction-specific guidance waits until the employer confirms the jurisdiction. */
    jurisdiction: "needs_confirmation" | null;
    expertReview: { active: boolean; scope: "action" | "matter" | null; actions: string[]; serviceAvailable: boolean };
  };
  checks: "ready" | "unavailable" | "not_applicable";
  latestOutcome: OutcomeKind | "none";
  /** Null: no Case (or an API from before M2-NEW-08). */
  position: CasePosition | null;
};
export type ConversationSummary = { id: string; title: string | null; case: CaseLink | null; createdAt: string; updatedAt: string };
export type Conversation = ConversationSummary & { revision: number; status: ConversationStatus };
export type GatewayTurn = { conversation: Conversation; messages: ConversationMessage[]; replayed: boolean };
export type ConversationList = { items: ConversationSummary[]; nextBefore: string | null };
export type MessagePage = { messages: ConversationMessage[]; nextBefore: number | null };
export type ConversationDetail = { conversation: Conversation; messages: ConversationMessage[]; nextBefore: number | null };
export type GatewayRequest = { message: string; turnKey: string; conversationId: string | null; expectedRevision: number };

const REASONS = new Set<string>(["disabled", "not_configured", "knowledge_unavailable"]);
const STATES = new Set<string>(["responded", "clarifying", "outside_approved_guidance"]);
const STEP_KINDS = new Set<string>(["guidance", "warning", "block", "expert_review"]);
const AUTHORS = new Set<string>(["you", "another_administrator", "heroos"]);
const LIFECYCLES = new Set<string>(["in_progress", "paused"]);
const CHECKS = new Set<string>(["ready", "unavailable", "not_applicable"]);
const LATEST = new Set<string>(["guidance", "warning", "block", "expert_review", "unavailable", "none"]);
const MAX_OUTCOME_ITEMS = 4;

type Naming = "api" | "bff";
type Fields = Record<string, unknown>;

const isRecord = (value: unknown): value is Fields => typeof value === "object" && value !== null && !Array.isArray(value);
// Control characters other than tab and line breaks.
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;
const validText = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max && !CONTROL.test(value);
const optionalText = (value: unknown, max = MAX_TEXT): value is string | null => value === null || validText(value, max);
const validInt = (value: unknown, min: number, max: number): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= min && value <= max;
const validTime = (value: unknown): value is string => typeof value === "string" && value.length <= 40 && !Number.isNaN(Date.parse(value));
const camel = (key: string) => key.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

/** The record's fields under the API's (snake_case) or the BFF's (camelCase) names; exactly those. */
function read(value: unknown, keys: readonly string[], naming: Naming): Fields | null {
  if (!isRecord(value)) return null;
  const names = keys.map((key) => (naming === "api" ? key : camel(key)));
  if (Object.keys(value).some((key) => !names.includes(key))) return null;
  return Object.fromEntries(keys.map((key, i) => [key, value[names[i]]]));
}

/** `GET /companies/{id}/assistant`, rebuilt field by field. */
export function fromApiGatewayStatus(body: unknown): GatewayStatus | null {
  if (!isRecord(body) || typeof body.available !== "boolean") return null;
  const reason = body.reason;
  if (reason !== null && (typeof reason !== "string" || !REASONS.has(reason))) return null;
  if (!optionalText(body.notice)) return null;
  return { available: body.available, reason: reason as GatewayUnavailable | null, notice: body.notice };
}

/**
 * The outcome card: exactly its four fields, known kinds, bounded text.
 * `undefined` for anything else (the whole answer is then refused).
 */
function outcomeOf(value: unknown): Outcome | null | undefined {
  if (value === null || value === undefined) return null;
  const card = read(value, ["kind", "title", "message", "items"], "api");
  if (card === null) return undefined;
  const { kind, title, message, items } = card;
  if (typeof kind !== "string" || !(STEP_KINDS.has(kind) || kind === "unavailable")) return undefined;
  if (!validText(title, 200) || !validText(message, 4000)) return undefined;
  if (!Array.isArray(items) || items.length > MAX_OUTCOME_ITEMS) return undefined;
  const steps: Outcome["items"] = [];
  for (const raw of items) {
    const item = read(raw, ["kind", "text"], "api");
    if (item === null || typeof item.kind !== "string" || !STEP_KINDS.has(item.kind) || !validText(item.text, 400)) return undefined;
    steps.push({ kind: item.kind as StepKind, text: item.text });
  }
  return { kind: kind as OutcomeKind, title, message, items: steps };
}

function messageOf(value: unknown, naming: Naming): ConversationMessage | null {
  const m = read(value, ["sequence", "author", "text", "safe_next_step", "conversation_state", "outcome", "created_at"], naming);
  if (m === null || !validInt(m.sequence, 1, 2 * MAX_REVISION) || typeof m.author !== "string" || !AUTHORS.has(m.author)) return null;
  if (!validText(m.text, MAX_TEXT) || !optionalText(m.safe_next_step) || !validTime(m.created_at)) return null;
  const state = m.conversation_state;
  if (state !== null && (typeof state !== "string" || !STATES.has(state))) return null;
  if ((m.author === "heroos") !== (state !== null)) return null;
  const outcome = outcomeOf(m.outcome);
  if (outcome === undefined) return null;
  return {
    sequence: m.sequence,
    author: m.author as Author,
    text: m.text,
    safeNextStep: m.safe_next_step,
    conversationState: state as ConversationState | null,
    outcome,
    createdAt: m.created_at,
  };
}

function messagesOf(value: unknown, naming: Naming): ConversationMessage[] | null {
  if (!Array.isArray(value) || value.length > MAX_ITEMS) return null;
  const messages = value.map((item) => messageOf(item, naming));
  return messages.some((m) => m === null) ? null : (messages as ConversationMessage[]);
}

function statusOf(value: unknown, naming: Naming): ConversationStatus | null {
  const s = read(value, ["lifecycle", "workflow", "attention", "checks", "latest_outcome", "position"], naming);
  if (s === null) return null;
  if (s.lifecycle !== null && (typeof s.lifecycle !== "string" || !LIFECYCLES.has(s.lifecycle))) return null;
  if (typeof s.checks !== "string" || !CHECKS.has(s.checks) || typeof s.latest_outcome !== "string" || !LATEST.has(s.latest_outcome)) return null;
  let workflow: ConversationStatus["workflow"] = null;
  if (s.workflow !== null) {
    const w = read(s.workflow, ["key", "title"], naming);
    if (w === null || typeof w.key !== "string" || !WORKFLOW_KEY.test(w.key) || !optionalText(w.title, MAX_TITLE)) return null;
    workflow = { key: w.key, title: w.title };
  }
  const a = read(s.attention, ["needs_information", "jurisdiction", "expert_review"], naming);
  if (a === null || typeof a.needs_information !== "boolean") return null;
  if (a.jurisdiction !== null && a.jurisdiction !== "needs_confirmation") return null;
  const r = read(a.expert_review, ["active", "scope", "actions", "service_available"], naming);
  if (r === null || typeof r.active !== "boolean" || typeof r.service_available !== "boolean") return null;
  if (r.scope !== null && r.scope !== "action" && r.scope !== "matter") return null;
  if (!Array.isArray(r.actions) || r.actions.length > MAX_REVIEW_ACTIONS || !r.actions.every((t) => validText(t, MAX_TITLE))) return null;
  let position: CasePosition | null = null;
  // Absent from an API before M2-NEW-08 (a web deploy may come first).
  if (s.position !== null && s.position !== undefined) {
    const p = read(s.position, ["state", "label", "pathway", "stage", "stage_in_progress", "held_steps"], naming);
    if (p === null || typeof p.state !== "string" || !WORKFLOW_KEY.test(p.state) || !validText(p.label, MAX_TITLE)) return null;
    if (!optionalText(p.pathway, MAX_TITLE) || !optionalText(p.stage, MAX_TITLE) || typeof p.stage_in_progress !== "boolean") return null;
    if (!Array.isArray(p.held_steps) || p.held_steps.length > MAX_REVIEW_ACTIONS || !p.held_steps.every((t) => validText(t, MAX_TITLE))) {
      return null;
    }
    position = {
      state: p.state,
      label: p.label,
      pathway: p.pathway,
      stage: p.stage,
      stageInProgress: p.stage_in_progress,
      heldSteps: [...(p.held_steps as string[])],
    };
  }
  return {
    lifecycle: s.lifecycle as ConversationStatus["lifecycle"],
    workflow,
    attention: {
      needsInformation: a.needs_information,
      jurisdiction: a.jurisdiction,
      expertReview: { active: r.active, scope: r.scope, actions: [...(r.actions as string[])], serviceAvailable: r.service_available },
    },
    checks: s.checks as ConversationStatus["checks"],
    latestOutcome: s.latest_outcome as ConversationStatus["latestOutcome"],
    position,
  };
}

const SUMMARY_KEYS = ["id", "title", "case", "created_at", "updated_at"] as const;

function summaryFields(s: Fields, naming: Naming): ConversationSummary | null {
  if (typeof s.id !== "string" || !UUID.test(s.id) || !optionalText(s.title, MAX_TITLE)) return null;
  if (!validTime(s.created_at) || !validTime(s.updated_at)) return null;
  let link: CaseLink | null = null;
  if (s.case !== null) {
    const c = read(s.case, ["id", "title"], naming);
    if (c === null || typeof c.id !== "string" || !UUID.test(c.id) || !validText(c.title, MAX_TITLE)) return null;
    link = { id: c.id, title: c.title };
  }
  return { id: s.id, title: s.title, case: link, createdAt: s.created_at, updatedAt: s.updated_at };
}

function summaryOf(value: unknown, naming: Naming): ConversationSummary | null {
  const s = read(value, SUMMARY_KEYS, naming);
  return s === null ? null : summaryFields(s, naming);
}

function conversationOf(value: unknown, naming: Naming): Conversation | null {
  const s = read(value, [...SUMMARY_KEYS, "revision", "status"], naming);
  if (s === null || !validInt(s.revision, 0, MAX_REVISION)) return null;
  const summary = summaryFields(s, naming);
  const status = statusOf(s.status, naming);
  return summary === null || status === null ? null : { ...summary, revision: s.revision, status };
}

function turnOf(body: unknown, naming: Naming): GatewayTurn | null {
  const t = read(body, ["conversation", "messages", "replayed"], naming);
  if (t === null || typeof t.replayed !== "boolean") return null;
  const conversation = conversationOf(t.conversation, naming);
  const messages = messagesOf(t.messages, naming);
  if (conversation === null || messages === null || messages.length !== 2) return null;
  if (messages[0].author === "heroos" || messages[1].author !== "heroos") return null;
  return { conversation, messages, replayed: t.replayed };
}

function listOf(body: unknown, naming: Naming): ConversationList | null {
  const l = read(body, ["items", "next_before"], naming);
  if (l === null || !Array.isArray(l.items) || l.items.length > MAX_ITEMS) return null;
  if (l.next_before !== null && (typeof l.next_before !== "string" || !CONVERSATION_CURSOR.test(l.next_before))) return null;
  const items = l.items.map((item) => summaryOf(item, naming));
  return items.some((i) => i === null) ? null : { items: items as ConversationSummary[], nextBefore: l.next_before };
}

function nextSequence(value: unknown): value is number | null {
  return value === null || validInt(value, 2, 2 * MAX_REVISION);
}

function pageOf(body: unknown, naming: Naming): MessagePage | null {
  const p = read(body, ["messages", "next_before"], naming);
  if (p === null || !nextSequence(p.next_before)) return null;
  const messages = messagesOf(p.messages, naming);
  return messages === null ? null : { messages, nextBefore: p.next_before };
}

function detailOf(body: unknown, naming: Naming): ConversationDetail | null {
  const d = read(body, ["conversation", "messages", "next_before"], naming);
  if (d === null || !nextSequence(d.next_before)) return null;
  const conversation = conversationOf(d.conversation, naming);
  const messages = messagesOf(d.messages, naming);
  return conversation === null || messages === null ? null : { conversation, messages, nextBefore: d.next_before };
}

/** `POST /companies/{id}/assistant/messages`, rebuilt field by field (nothing else is passed on). */
export const fromApiGatewayTurn = (body: unknown) => turnOf(body, "api");
/** `GET /companies/{id}/assistant/conversations`. */
export const fromApiConversationList = (body: unknown) => listOf(body, "api");
/** `GET /companies/{id}/assistant/conversations/{conversationId}`. */
export const fromApiConversationDetail = (body: unknown) => detailOf(body, "api");
/** `GET .../conversations/{conversationId}/messages`. */
export const fromApiMessagePage = (body: unknown) => pageOf(body, "api");

/** The BFF's answers as the browser reads them (the same shapes, checked again). */
export const parseGatewayTurn = (body: unknown) => turnOf(body, "bff");
export const parseConversationList = (body: unknown) => listOf(body, "bff");
export const parseConversationDetail = (body: unknown) => detailOf(body, "bff");
export const parseMessagePage = (body: unknown) => pageOf(body, "bff");

/** The browser's request, re-validated and rebuilt by the BFF (unknown keys refused). */
export function parseGatewayRequest(body: unknown): { ok: true; value: GatewayRequest } | { ok: false } {
  if (!isRecord(body) || Object.keys(body).some((key) => !["message", "turnKey", "conversationId", "expectedRevision"].includes(key))) {
    return { ok: false };
  }
  const conversationId = body.conversationId ?? null;
  if (!validText(body.message, MAX_MESSAGE_CHARS)) return { ok: false };
  if (typeof body.turnKey !== "string" || !UUID.test(body.turnKey)) return { ok: false };
  if (conversationId !== null && (typeof conversationId !== "string" || !UUID.test(conversationId))) return { ok: false };
  if (!validInt(body.expectedRevision, 0, MAX_REVISION) || (conversationId === null && body.expectedRevision !== 0)) {
    return { ok: false };
  }
  return { ok: true, value: { message: body.message, turnKey: body.turnKey, conversationId, expectedRevision: body.expectedRevision } };
}

/** What the browser sends for a message: its words, its turn key, the conversation and the revision it saw. */
export function gatewayRequest(message: string, turnKey: string, conversationId: string | null, expectedRevision: number): GatewayRequest {
  return { message, turnKey, conversationId, expectedRevision: conversationId === null ? 0 : expectedRevision };
}

/** A message sequence query value (`before`) the BFF may pass on. */
export function parseSequence(value: string | null): number | null | undefined {
  if (value === null) return null;
  if (!/^[0-9]{1,6}$/.test(value)) return undefined;
  const sequence = Number(value);
  return sequence >= 2 && sequence <= 2 * MAX_REVISION + 1 ? sequence : undefined;
}
