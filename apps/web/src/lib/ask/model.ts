import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

/**
 * Ask HeroOS (M2-NEW-02): the founder explains a situation in their own words
 * and HeroOS opens the case. There is no AI behind it yet: until M2-NEW-05/06
 * connect the AI conversation, the question opens a case of the reference
 * workflow (Disciplinary, the only one HeroOS runs today) and the founder's
 * words are saved as its first fact, exactly as written. Everything goes
 * through one seam (`POST /bff/companies/{id}/ask`), which those issues
 * repoint at the AI gateway.
 */

/** The workflow a question opens today. */
export const ASK_WORKFLOW = WORKFLOW_DISCIPLINARY;
/** Where the founder's own words are saved: the first question of the Disciplinary intake. */
export const ASK_STEP = "initial_facts";
export const ASK_QUESTION = "incident.narrative";
/** The API's limit for that answer. */
export const ASK_TEXT_MAX = 4000;

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

/**
 * A neutral case name until HeroOS names cases itself (M2-NEW-05/07): when it
 * was opened, in the founder's own time zone, and never the founder's words
 * (which may name an employee).
 */
export function provisionalCaseTitle(at: Date): string {
  return `New case · ${DAY.format(at)}, ${TIME.format(at)}`;
}

/** The BFF's answer: the case opened, and whether the founder's words were saved into it. */
export type AskStarted = { caseId: string; narrativeSaved: boolean };

export function parseAskStarted(body: unknown): AskStarted | null {
  if (typeof body !== "object" || body === null) return null;
  const { caseId, narrativeSaved } = body as Record<string, unknown>;
  if (typeof caseId !== "string" || !/^[0-9a-f-]{36}$/.test(caseId) || typeof narrativeSaved !== "boolean") return null;
  return { caseId, narrativeSaved };
}
