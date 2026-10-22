import { AlertIcon, CaseIcon, HelpIcon, PeopleIcon } from "@/components/site/icons";
import type { Conversation } from "@/lib/ask/conversation";

/**
 * What a reopened conversation is about, now (M2-NEW-07): its Case (title,
 * link) and the status's separate dimensions, never one badge for all of them.
 *
 * - Lifecycle is the Case's own: in progress, or paused while the whole
 *   matter is held. An action's Expert Review never pauses it.
 * - Attention says what is needed: information, the jurisdiction confirmed,
 *   an Expert Review (before which decision, or for the whole matter). Expert
 *   Review is a requirement, never a ticket: nothing here says it was sent.
 * - Checks that can't run now are a technical note, never the Case's status.
 *
 * - Position (M2-NEW-08) is where the Case's formal workflow stands, as its
 *   employer recorded it: the pathway (their decision, never HeroOS's) and the
 *   stage in progress or next. A Case step the progression rules hold for
 *   specialist review is its own note, apart from a decision's Expert Review.
 *
 * The outcome of each turn stays on that turn (its own Guidance, Warning,
 * Block or Expert Review per step), so it isn't repeated here.
 */

const LIFECYCLE = { in_progress: "In progress", paused: "Paused" } as const;

/** "Dismissal without notice" → "dismissal without notice", leaving an acronym ("DIFC …") as it is. */
function inSentence(title: string): string {
  return /^[A-Z][a-z]/.test(title) ? title.charAt(0).toLowerCase() + title.slice(1) : title;
}

function joined(titles: string[]): string {
  const words = titles.map(inSentence);
  return words.length <= 1 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words.at(-1)}`;
}

/** The Expert Review requirement in words, or null when none is active. */
export function expertReviewText(review: Conversation["status"]["attention"]["expertReview"]): string | null {
  if (!review.active) return null;
  if (review.scope === "action" && review.actions.length > 0) return `Expert review required before ${joined(review.actions)}`;
  return "Expert review required for this matter";
}

const chip = "inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.8125rem] font-semibold";

export function ConversationContext({ companyId, conversation }: { companyId: string; conversation: Conversation }) {
  const { status } = conversation;
  const review = expertReviewText(status.attention.expertReview);
  const needs = status.attention.needsInformation;
  const jurisdiction = status.attention.jurisdiction === "needs_confirmation";
  const unavailable = status.checks === "unavailable";
  const position = status.position;
  const held = position?.heldSteps ?? [];
  if (conversation.case === null && review === null && !unavailable) return null;
  const caseHref = conversation.case
    ? `/workspaces/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(conversation.case.id)}`
    : null;
  return (
    <section aria-label="About this conversation" className="mt-3 rounded-2xl border border-hero-navy/[0.08] bg-white/80 px-4 py-3">
      {conversation.case && caseHref ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.9375rem]">
          <CaseIcon className="size-4 shrink-0 text-hero-muted" />
          <a className="min-w-0 truncate font-bold text-hero-navy underline-offset-2 hover:underline" href={caseHref}>
            {conversation.case.title}
          </a>
          {status.lifecycle ? (
            <span className="text-[0.8125rem] font-semibold text-hero-muted">· {LIFECYCLE[status.lifecycle]}</span>
          ) : null}
          <a className="ml-auto text-[0.8125rem] font-bold text-hero-blue-ink underline" href={caseHref}>
            Open case
          </a>
        </p>
      ) : null}
      {position && position.state !== "unavailable" ? (
        <p className="mt-1 text-[0.8125rem] text-hero-muted">
          {position.pathway ? (
            <>
              <span className="font-semibold text-hero-navy">{position.pathway}</span> (your decision)
            </>
          ) : (
            "No pathway recorded yet"
          )}
          {position.stage ? ` · ${position.stage}${position.stageInProgress ? " in progress" : " is next"}` : ` · ${position.label}`}
        </p>
      ) : null}
      {review || needs || jurisdiction || held.length > 0 ? (
        <ul aria-label="Needs attention" className={`flex flex-wrap gap-2 ${conversation.case ? "mt-2" : ""}`}>
          {review ? (
            <li className={`${chip} tone-expert border-transparent bg-(--tone-chip) text-(--tone-ink)`}>
              <PeopleIcon className="size-3.5 shrink-0" />
              {review}
            </li>
          ) : null}
          {held.length > 0 ? (
            <li className={`${chip} tone-expert border-transparent bg-(--tone-chip) text-(--tone-ink)`}>
              <PeopleIcon className="size-3.5 shrink-0" />
              Specialist review needed before: {held.join(", ")}
            </li>
          ) : null}
          {jurisdiction ? (
            <li className={`${chip} border-hero-border bg-white text-hero-navy`}>
              <HelpIcon className="size-3.5 shrink-0" />
              Jurisdiction to confirm
            </li>
          ) : null}
          {needs ? (
            <li className={`${chip} border-hero-border bg-white text-hero-navy`}>
              <HelpIcon className="size-3.5 shrink-0" />
              Needs information
            </li>
          ) : null}
        </ul>
      ) : null}
      {unavailable ? (
        <p className="mt-2 flex items-center gap-1.5 text-[0.8125rem] text-hero-muted" role="note">
          <AlertIcon className="size-3.5 shrink-0" />
          HeroOS&apos;s checks are temporarily unavailable.
        </p>
      ) : null}
    </section>
  );
}
