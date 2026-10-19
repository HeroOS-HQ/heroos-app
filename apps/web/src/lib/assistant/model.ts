/**
 * The Hannah AI demo (conversational, fictional scenarios only): shapes, limits
 * and the bounded history the browser sends. The conversation lives in React
 * state only: never stored, never written into the Case.
 *
 * The limits match the API (app/api/assistant.py), which checks them again.
 */

export type ChatRole = "user" | "assistant";
export type ChatTurn = { role: ChatRole; content: string };

export const MAX_MESSAGE_CHARS = 2000;
export const MAX_TURN_CHARS = 4000;
export const MAX_HISTORY_TURNS = 12;
export const MAX_HISTORY_CHARS = 8000;

export type AssistantUnavailable = "disabled" | "not_configured";
export type AssistantStatus = {
  available: boolean;
  reason: AssistantUnavailable | null;
  notice: string;
};
export type AssistantReply = {
  reply: string;
  provider: string;
  model: string;
  notice: string;
};
export type AssistantRequest = { message: string; history: ChatTurn[] };

/**
 * What the case page knows about the demo for this administrator and Case:
 * `hidden` (switched off here, not for this person, or an API without the
 * demo: the page shows the guided workflow alone), `unreachable` (the status
 * couldn't be read: say so and offer a re-check, never a pretend chat) or the
 * API's `ready` status.
 */
export type AssistantLoad =
  | { state: "hidden" }
  | { state: "unreachable" }
  | { state: "ready"; status: AssistantStatus };

export const ASSISTANT_HIDDEN: AssistantLoad = { state: "hidden" };

/** The status as the page uses it: a switched-off demo stays out of sight. */
export function assistantLoadOf(status: AssistantStatus): AssistantLoad {
  return status.reason === "disabled" ? ASSISTANT_HIDDEN : { state: "ready", status };
}

const REASONS = new Set<string>(["disabled", "not_configured"]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function isAssistantStatus(value: unknown): value is AssistantStatus {
  return (
    isRecord(value) &&
    typeof value.available === "boolean" &&
    (value.reason === null || (typeof value.reason === "string" && REASONS.has(value.reason))) &&
    typeof value.notice === "string"
  );
}

export function isAssistantReply(value: unknown): value is AssistantReply {
  return (
    isRecord(value) &&
    typeof value.reply === "string" &&
    value.reply.trim().length > 0 &&
    typeof value.provider === "string" &&
    typeof value.model === "string" &&
    typeof value.notice === "string"
  );
}

/** The API's answers, rebuilt field by field (nothing else is passed on). */
export function fromApiAssistantStatus(body: unknown): AssistantStatus | null {
  return isAssistantStatus(body) ? { available: body.available, reason: body.reason, notice: body.notice } : null;
}

export function fromApiAssistantReply(body: unknown): AssistantReply | null {
  return isAssistantReply(body)
    ? {
        reply: body.reply,
        provider: body.provider,
        model: body.model,
        notice: body.notice,
      }
    : null;
}

// Control characters other than tab and line breaks.
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

const validText = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max && !CONTROL.test(value);

/**
 * The most recent turns that fit the limits, oldest first, each cut to
 * `MAX_TURN_CHARS`, starting with one of the employer's turns.
 */
export function boundedHistory(turns: readonly ChatTurn[]): ChatTurn[] {
  const kept: ChatTurn[] = [];
  let budget = MAX_HISTORY_CHARS;
  for (const turn of [...turns].reverse()) {
    if (kept.length === MAX_HISTORY_TURNS) break;
    const content = turn.content.slice(0, MAX_TURN_CHARS);
    if (!validText(content, MAX_TURN_CHARS)) continue;
    budget -= content.length;
    if (budget < 0) break;
    kept.unshift({ role: turn.role, content });
  }
  while (kept.length > 0 && kept[0].role !== "user") kept.shift();
  return kept;
}

/** The browser's request, re-validated and rebuilt by the BFF (unknown keys refused). */
export function parseAssistantRequest(body: unknown): { ok: true; value: AssistantRequest } | { ok: false } {
  if (!isRecord(body) || Object.keys(body).some((key) => key !== "message" && key !== "history")) return { ok: false };
  if (!validText(body.message, MAX_MESSAGE_CHARS)) return { ok: false };
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
  return { ok: true, value: { message: body.message, history } };
}
