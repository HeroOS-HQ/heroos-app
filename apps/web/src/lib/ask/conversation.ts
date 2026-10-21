import { boundedHistory, type ChatTurn, MAX_HISTORY_TURNS, MAX_MESSAGE_CHARS, MAX_TURN_CHARS } from "@/lib/assistant/model";

/**
 * Ask HeroOS's AI conversation (M2-NEW-05): shapes, limits and the bounded
 * history the browser sends to the controlled gateway
 * (`POST /bff/companies/{id}/assistant/messages`). The founder writes in their
 * own words; there is no Case, workflow, category or stage to choose.
 *
 * The conversation lives in React state only: never stored, never written
 * into a Case. Each reply carries an opaque `continuation` (what HeroOS last
 * asked about, signed by the API) that the next message sends back
 * unchanged. Nothing here decides anything: `conversationState` says how a
 * turn was handled, never Guidance, Warning, Block or Expert Review
 * (M2-NEW-06 connects those to the deterministic engine).
 *
 * The limits match the API (app/api/gateway.py), which checks them again.
 */

export { MAX_MESSAGE_CHARS };
export const MAX_CONTINUATION_CHARS = 512;
const CONTINUATION = /^[A-Za-z0-9_-]{1,400}\.[A-Za-z0-9_-]{1,100}$/;

export type GatewayUnavailable = "disabled" | "not_configured" | "knowledge_unavailable";
export type GatewayStatus = { available: boolean; reason: GatewayUnavailable | null; notice: string | null };

export type ConversationState = "responded" | "clarifying" | "outside_approved_guidance";
export type GatewayReply = {
  reply: string;
  safeNextStep: string | null;
  conversationState: ConversationState;
  continuation: string;
};
export type GatewayRequest = { message: string; history: ChatTurn[]; continuation: string | null };

const REASONS = new Set<string>(["disabled", "not_configured", "knowledge_unavailable"]);
const STATES = new Set<string>(["responded", "clarifying", "outside_approved_guidance"]);

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

/** `POST /companies/{id}/assistant/messages`, rebuilt field by field (nothing else is passed on). */
export function fromApiGatewayReply(body: unknown): GatewayReply | null {
  if (!isRecord(body)) return null;
  const { reply, safe_next_step: step, conversation_state: state, continuation } = body;
  if (typeof reply !== "string" || reply.trim().length === 0 || !optionalText(step)) return null;
  if (typeof state !== "string" || !STATES.has(state) || !validContinuation(continuation)) return null;
  return { reply, safeNextStep: step, conversationState: state as ConversationState, continuation };
}

/** The BFF's answer as the browser reads it. */
export function parseGatewayReply(body: unknown): GatewayReply | null {
  if (!isRecord(body)) return null;
  return fromApiGatewayReply({
    reply: body.reply,
    safe_next_step: body.safeNextStep,
    conversation_state: body.conversationState,
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
