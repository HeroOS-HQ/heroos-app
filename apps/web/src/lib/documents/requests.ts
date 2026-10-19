import { CHOICE_KEY, FIELD_KEY, OPTION_VALUE } from "./model";

/**
 * Browser → BFF preview requests (M2-04C), re-validated on the web server and
 * rebuilt field by field (unknown keys refused) before they reach the HeroOS
 * API. The API validates every value against the template and decides; these
 * checks only keep malformed or oversized requests away from it.
 */

export type ParsedRequest<T> = { ok: true; value: T } | { ok: false };
export type PreviewPayload = {
  template_version: number;
  values: Record<string, string | string[]>;
  choices: Record<string, string[]>;
};

/** Bounds on the request, matching the API's (not product rules). */
export const MAX_VALUES = 60;
export const MAX_VALUE_LENGTH = 4000;
export const MAX_LIST_ITEMS = 30;
export const MAX_CHOICES = 8;
export const MAX_OPTIONS = 8;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const onlyKeys = (value: Json, keys: string[]) => Object.keys(value).every((key) => keys.includes(key));
const isValueText = (value: unknown): value is string => typeof value === "string" && value.length <= MAX_VALUE_LENGTH;

export function parsePreviewRequest(body: unknown): ParsedRequest<PreviewPayload> {
  if (!isRecord(body) || !onlyKeys(body, ["templateVersion", "values", "choices"])) return { ok: false };
  const { templateVersion, values, choices } = body;
  if (
    typeof templateVersion !== "number" ||
    !Number.isInteger(templateVersion) ||
    templateVersion < 1 ||
    !isRecord(values) ||
    !isRecord(choices)
  ) {
    return { ok: false };
  }
  const valueEntries = Object.entries(values);
  const choiceEntries = Object.entries(choices);
  if (valueEntries.length > MAX_VALUES || choiceEntries.length > MAX_CHOICES) return { ok: false };

  const rebuiltValues: Record<string, string | string[]> = {};
  for (const [key, value] of valueEntries) {
    if (!FIELD_KEY.test(key)) return { ok: false };
    if (isValueText(value)) rebuiltValues[key] = value;
    else if (Array.isArray(value) && value.length <= MAX_LIST_ITEMS && value.every(isValueText)) rebuiltValues[key] = [...value];
    else return { ok: false };
  }
  const rebuiltChoices: Record<string, string[]> = {};
  for (const [key, selected] of choiceEntries) {
    if (
      !CHOICE_KEY.test(key) ||
      !Array.isArray(selected) ||
      selected.length > MAX_OPTIONS ||
      !selected.every((value) => typeof value === "string" && OPTION_VALUE.test(value))
    ) {
      return { ok: false };
    }
    rebuiltChoices[key] = [...(selected as string[])];
  }
  return { ok: true, value: { template_version: templateVersion, values: rebuiltValues, choices: rebuiltChoices } };
}
