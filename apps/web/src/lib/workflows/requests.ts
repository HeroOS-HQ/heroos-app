import { FACT_KEY, TITLE_MAX, UUID } from "./model";

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
