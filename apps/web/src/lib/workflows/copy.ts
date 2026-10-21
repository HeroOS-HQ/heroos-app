import { NOT_SURE, type ProgressStatus, type Question } from "./model";

/**
 * Wording for the guided workflow screens. Statuses are always written in
 * words; tones only reinforce them. Dates are shown in UTC so the server and the
 * browser render the same text.
 */

export type Tone = "positive" | "neutral" | "caution" | "muted";

export const PROGRESS_COPY: Record<ProgressStatus, { label: string; tone: Tone }> = {
  completed: { label: "Completed", tone: "positive" },
  in_progress: { label: "In progress", tone: "neutral" },
  needs_information: { label: "Needs information", tone: "caution" },
  blocked: { label: "Blocked", tone: "caution" },
  coming_later: { label: "Coming later", tone: "muted" },
};

/**
 * The quiet dot beside a Case status in the workspace (Cases drawer, case
 * pill). It supports the API's words and never replaces them: dark pink when
 * the case waits for a specialist (Expert Review), grey while HeroOS or the
 * environment has to act, blue when the next move is the employer's.
 */
export function caseStatusDot(code: string): string {
  switch (code) {
    case "held_for_specialist_review":
      return "bg-[#a92f6c]";
    case "awaiting_jurisdiction":
    case "screening_unavailable":
      return "bg-hero-control";
    default:
      return "bg-hero-blue";
  }
}

/** Tone of a Case status chosen by the API; unknown codes stay neutral. */
export function caseStatusTone(code: string): Tone {
  switch (code) {
    case "intake_recorded":
      return "positive";
    case "awaiting_jurisdiction":
    case "screening_not_cleared":
    case "screening_unavailable":
    case "held_for_specialist_review":
      return "caution";
    default:
      return "neutral";
  }
}

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const DAY_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

export function formatDay(iso: string): string {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? "" : DAY.format(time);
}

export function formatDayTime(iso: string): string {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? "" : `${DAY_TIME.format(time)} UTC`;
}

/** A saved answer as the employer gave it (option label, readable date); never interpreted. */
export function displayAnswer(question: Question, value: string): string {
  if (question.kind === "choice") return question.options.find((option) => option.value === value)?.label ?? value;
  if (question.kind === "date") {
    if (value === NOT_SURE) return "Not sure";
    const day = formatDay(`${value}T00:00:00Z`);
    return day || value;
  }
  return value;
}
