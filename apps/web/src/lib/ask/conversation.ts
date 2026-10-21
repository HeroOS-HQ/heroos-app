import { boundedHistory, type ChatTurn, MAX_HISTORY_TURNS, MAX_MESSAGE_CHARS, MAX_TURN_CHARS } from "@/lib/assistant/model";

/**
 * Ask HeroOS's AI conversation (M2-NEW-05): shapes, limits and the bounded
 * history the browser sends to the controlled gateway
 * (`POST /bff/companies/{id}/assistant/messages`). The founder writes in their
 * own words; there is no Case, workflow, category or stage to choose.
 *
 * The conversation lives in React state only: never stored, never written
 * into a Case. Each reply carries an opaque `continuation` (encrypted by the
 * API: what HeroOS last asked and the state its checks trust) that the next
 * message sends back unchanged. Nothing here decides anything: the `outcome`
 * (Guidance, Warning, Block, Expert Review, or checks unavailable) is the
 * API's deterministic result in its own words (M2-NEW-06), shown as given;
 * the browser never sends or changes one. `conversationState` only says how
 * a turn was handled.
 *
 * The limits match the API (app/api/gateway.py), which checks them again.
 */

export { MAX_MESSAGE_CHARS };
export const MAX_CONTINUATION_CHARS = 2400;
// An opaque token: the current encrypted form, or an earlier signed one (the API
// then treats it as lost state, re-confirmed, so a deploy never breaks a conversation).
const CONTINUATION = /^[A-Za-z0-9_-]{1,40}(?:\.[A-Za-z0-9_-]{1,2380}){1,2}$/;

export type GatewayUnavailable = "disabled" | "not_configured" | "knowledge_unavailable";
export type GatewayStatus = { available: boolean; reason: GatewayUnavailable | null; notice: string | null };

export type ConversationState = "responded" | "clarifying" | "outside_approved_guidance";
/** The deterministic outcome HeroOS's checks decided; "unavailable" is technical, never an HR outcome. */
export type OutcomeKind = "guidance" | "warning" | "block" | "expert_review" | "unavailable";
export type StepKind = Exclude<OutcomeKind, "unavailable">;
export type Outcome = { kind: OutcomeKind; title: string; message: string; items: { kind: StepKind; text: string }[] };
export type GatewayReply = {
  reply: string;
  safeNextStep: string | null;
  conversationState: ConversationState;
  outcome: Outcome | null;
  continuation: string;
};
export type GatewayRequest = { message: string; history: ChatTurn[]; continuation: string | null };

const REASONS = new Set<string>(["disabled", "not_configured", "knowledge_unavailable"]);
const STATES = new Set<string>(["responded", "clarifying", "outside_approved_guidance"]);
const STEP_KINDS = new Set<string>(["guidance", "warning", "block", "expert_review"]);
const MAX_OUTCOME_ITEMS = 4;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
// Control characters other than tab and line breaks.
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
const validText = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max && !CONTROL.test(value);
const optionalText = (value: unknown): value is string | null => value === null || (typeof value === "string" && value.trim().length > 0);
const validContinuation = (value: unknown): value is string =>
  typeof value === "string" && value.length <= MAX_CONTINUATION_CHARS && CONTINUATION.test(value);

/** `GET /companies/{id}/assistant`, rebuilt field by field. */
export function fromApiGatewayStatus(body: unknown): GatewayStatus | null {
  if (!isRecord(body) || typeof body.available !== "boolean") return null;
  const reason = body.reason;
  if (reason !== null && (typeof reason !== "string" || !REASONS.has(reason))) return null;
  if (!optionalText(body.notice)) return null;
  return { available: body.available, reason: reason as GatewayUnavailable | null, notice: body.notice };
}

/**
 * The outcome card, rebuilt field by field: exactly its four fields, known kinds, bounded text.
 * `undefined` for anything else (the whole reply is then refused). An API without
 * outcomes (before M2-NEW-06) sends none: that's no outcome, not an error.
 */
function fromApiOutcome(value: unknown): Outcome | null | undefined {
  if (value === null || value === undefined) return null;
  if (!isRecord(value) || Object.keys(value).some((key) => !["kind", "title", "message", "items"].includes(key))) return undefined;
  const { kind, title, message, items } = value;
  if (typeof kind !== "string" || !(STEP_KINDS.has(kind) || kind === "unavailable")) return undefined;
  if (!validText(title, 200) || !validText(message, 4000)) return undefined;
  if (!Array.isArray(items) || items.length > MAX_OUTCOME_ITEMS) return undefined;
  const steps: Outcome["items"] = [];
  for (const item of items) {
    if (!isRecord(item) || Object.keys(item).some((key) => key !== "kind" && key !== "text")) return undefined;
    if (typeof item.kind !== "string" || !STEP_KINDS.has(item.kind) || !validText(item.text, 400)) return undefined;
    steps.push({ kind: item.kind as StepKind, text: item.text });
  }
  return { kind: kind as OutcomeKind, title, message, items: steps };
}

/** `POST /companies/{id}/assistant/messages`, rebuilt field by field (nothing else is passed on). */
export function fromApiGatewayReply(body: unknown): GatewayReply | null {
  if (!isRecord(body)) return null;
  const { reply, safe_next_step: step, conversation_state: state, continuation } = body;
  if (typeof reply !== "string" || reply.trim().length === 0 || !optionalText(step)) return null;
  if (typeof state !== "string" || !STATES.has(state) || !validContinuation(continuation)) return null;
  const outcome = fromApiOutcome(body.outcome);
  if (outcome === undefined) return null;
  return { reply, safeNextStep: step, conversationState: state as ConversationState, outcome, continuation };
}

/** The BFF's answer as the browser reads it. */
export function parseGatewayReply(body: unknown): GatewayReply | null {
  if (!isRecord(body)) return null;
  return fromApiGatewayReply({
    reply: body.reply,
    safe_next_step: body.safeNextStep,
    conversation_state: body.conversationState,
    outcome: body.outcome,
    continuation: body.continuation,
  });
}

/** The browser's request, re-validated and rebuilt by the BFF (unknown keys refused). */
export function parseGatewayRequest(body: unknown): { ok: true; value: GatewayRequest } | { ok: false } {
  if (!isRecord(body) || Object.keys(body).some((key) => !["message", "history", "continuation"].includes(key))) {
    return { ok: false };
  }
  if (!validText(body.message, MAX_MESSAGE_CHARS)) return { ok: false };
  const continuation = body.continuation ?? null;
  if (continuation !== null && !validContinuation(continuation)) return { ok: false };
  const raw = body.history ?? [];
  if (!Array.isArray(raw) || raw.length > MAX_HISTORY_TURNS) return { ok: false };
  const history: ChatTurn[] = [];
  for (const item of raw) {
    if (
      !isRecord(item) ||
      Object.keys(item).some((key) => key !== "role" && key !== "content") ||
      (item.role !== "user" && item.role !== "assistant") ||
      !validText(item.content, MAX_TURN_CHARS)
    ) {
      return { ok: false };
    }
    history.push({ role: item.role, content: item.content });
  }
  return { ok: true, value: { message: body.message, history, continuation } };
}

/** What the browser sends for a new message: the message, the recent turns, the last continuation. */
export function gatewayRequest(message: string, turns: readonly ChatTurn[], continuation: string | null): GatewayRequest {
  return { message, history: boundedHistory(turns), continuation };
}
