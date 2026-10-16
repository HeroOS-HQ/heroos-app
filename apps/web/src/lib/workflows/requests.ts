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
