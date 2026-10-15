import { NOT_SURE, type Question, type Step } from "./model";

/**
 * The answer form of one step: a text value per question (`"not_sure"` for an
 * unknown date, `""` for unanswered), validated here for the user's benefit
 * only. The HeroOS API validates again and decides what is stored.
 *
 * Only changed answers are sent. Emptying a question that has a saved answer
 * clears it (`null`); answers are trimmed, never otherwise rewritten.
 */

export type Draft = Record<string, string>;
export type AnswerErrors = Record<string, string>;
export type AnswerPatch = Record<string, string | null>;

/** Control characters other than line breaks and tabs. */
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function draftFrom(step: Step, answers: Record<string, string>): Draft {
  return Object.fromEntries(step.questions.map((question) => [question.key, answers[question.key] ?? ""]));
}

/** `YYYY-MM-DD` for a date in the user's own calendar. */
export function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function errorFor(question: Question, value: string, today: string): string | null {
  if (question.kind === "text") {
    if (question.maxLength !== null && value.length > question.maxLength) {
      return `Please keep this to ${question.maxLength.toLocaleString("en-GB")} characters or fewer.`;
    }
    if (CONTROL.test(value)) return "Please remove unusual control characters.";
    return null;
  }
  if (question.kind === "date") {
    if (question.allowNotSure && value === NOT_SURE) return null;
    if (!ISO_DATE.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) return "Please enter a valid date.";
    if (value > today) return "The date can't be in the future.";
    if (value < "1990-01-01") return "Please check the year.";
    return null;
  }
  return question.options.some((option) => option.value === value) ? null : "Please choose one of the options.";
}

/** The changed answers to send, or the problems to show first. */
export function buildAnswers(
  step: Step,
  draft: Draft,
  saved: Record<string, string>,
  today: string = isoDay(new Date()),
): { answers: AnswerPatch; errors: AnswerErrors } {
  const answers: AnswerPatch = {};
  const errors: AnswerErrors = {};
  for (const question of step.questions) {
    const raw = draft[question.key] ?? "";
    const value = question.kind === "text" ? raw.trim() : raw;
    const before = saved[question.key];
    if (value === "") {
      if (before !== undefined) answers[question.key] = null;
      continue;
    }
    const error = errorFor(question, value, today);
    if (error) errors[question.key] = error;
    else if (value !== before) answers[question.key] = value;
  }
  return { answers, errors };
}

export function changedCount(patch: AnswerPatch): number {
  return Object.keys(patch).length;
}
