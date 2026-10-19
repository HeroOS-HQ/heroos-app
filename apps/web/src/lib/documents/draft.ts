import type { ChoiceSpec, FieldSpec, TemplateForm } from "./model";

/**
 * A template form's draft (M2-04C): what the administrator typed, held in the
 * page's memory only (never in browser storage, never sent anywhere but to the
 * preview), the checks the browser can make before asking for a preview (the
 * API checks everything again), and the request body for the BFF. Values are
 * trimmed, never otherwise rewritten; an empty field is simply left out and
 * shows as a gap in the preview. Client-safe and pure.
 */

export type DraftValues = Record<string, string | string[]>;
export type DraftChoices = Record<string, string[]>;
export type DraftErrors = Record<string, string>;

const DAY = /^\d{4}-\d{2}-\d{2}$/;
// What the API refuses as invisible: control, format (bidi, zero-width),
// private-use and unassigned characters, line or paragraph separators, and any
// space other than the ordinary one. Line breaks and tabs are fine in long text.
const INVISIBLE = /[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Cn}\p{Zl}\p{Zp}]|(?! )\p{Zs}/u;
const plural = (count: number) => count.toLocaleString("en-GB");

/** The draft a form starts with: suggestions filled in, everything else empty. */
export function initialValues(form: TemplateForm): DraftValues {
  return Object.fromEntries(
    form.fields.map((field) => [field.key, field.kind === "list" ? [""] : (field.suggested ?? "")]),
  );
}

function realDate(value: string): boolean {
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function lineError(value: string, max: number, multiLine: boolean): string | null {
  const visible = multiLine ? value.replace(/[\n\t]/g, "") : value;
  if (INVISIBLE.test(visible)) return "Remove the invisible or special characters (they can come from copying and pasting).";
  if (value.length > max) return `Keep it to ${plural(max)} characters or fewer.`;
  return null;
}

function fieldError(field: FieldSpec, value: string | string[] | undefined): string | null {
  if (value === undefined) return null;
  if (field.kind === "list") {
    const entries = (Array.isArray(value) ? value : [value]).map((entry) => entry.trim()).filter((entry) => entry !== "");
    if (field.maxItems !== null && entries.length > field.maxItems) return `List at most ${plural(field.maxItems)} entries.`;
    for (const entry of entries) {
      const error = lineError(entry, field.maxLength ?? 0, false);
      if (error) return error;
    }
    return null;
  }
  const text = (Array.isArray(value) ? value.join(" ") : value).trim();
  if (text === "") return null;
  if (field.kind === "date") {
    if (!DAY.test(text) || !realDate(text)) return "Enter a real date.";
    if (text < "1990-01-01" || text > "2100-12-31") return "Check the year: it must be between 1990 and 2100.";
    return null;
  }
  return lineError(text, field.maxLength ?? 0, field.kind === "long_text");
}

/** Field errors by field key (choices can't be wrong in the form: they are radio buttons or checkboxes). */
export function checkDraft(form: TemplateForm, values: DraftValues): DraftErrors {
  const errors: DraftErrors = {};
  for (const field of form.fields) {
    const error = fieldError(field, values[field.key]);
    if (error) errors[field.key] = error;
  }
  return errors;
}

/** The BFF request body: filled fields and made choices only (camelCase; rebuilt on the web server). */
export function previewBody(form: TemplateForm, values: DraftValues, choices: DraftChoices): Record<string, unknown> {
  const filled: Record<string, string | string[]> = {};
  for (const field of form.fields) {
    const value = values[field.key];
    if (value === undefined) continue;
    if (field.kind === "list") {
      const entries = (Array.isArray(value) ? value : [value]).map((entry) => entry.trim()).filter((entry) => entry !== "");
      if (entries.length > 0) filled[field.key] = entries;
      continue;
    }
    const text = (Array.isArray(value) ? value.join(" ") : value).trim();
    if (text !== "") filled[field.key] = text;
  }
  const made: Record<string, string[]> = {};
  for (const choice of form.choices) {
    const selected = (choices[choice.key] ?? []).filter((value) => choice.options.some((option) => option.value === value));
    if (selected.length > 0) made[choice.key] = choice.multiple ? selected : selected.slice(0, 1);
  }
  return { templateVersion: form.template.version, values: filled, choices: made };
}

/** Toggle an option of a choice (one option for a single choice, any number otherwise). */
export function toggleChoice(choice: ChoiceSpec, current: string[], value: string): string[] {
  if (!choice.multiple) return [value];
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}
