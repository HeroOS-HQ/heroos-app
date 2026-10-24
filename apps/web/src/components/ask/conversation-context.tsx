import type { ReactNode } from "react";

import { AlertIcon, CaseIcon, HelpIcon, PeopleIcon, PlusIcon } from "@/components/site/icons";
import type { Conversation } from "@/lib/ask/conversation";

/**
 * The Case header over its chat (chat-first: one chat is one Case). Light, so
 * the conversation stays the page: the Case's title (the server's, "New case"
 * until HeroOS knows what the matter is), where it stands in a few words, and
 * the secondary ways in: Case details (the structured record, once the Case
 * has a workflow), History and New chat. Under it, only what needs attention,
 * as separate dimensions, never one badge for all of them:
 *
 * - Lifecycle is the Case's own: in progress, or paused while the whole
 *   matter is held. An action's Expert Review never pauses it.
 * - Attention: an Expert Review (before which decision, or for the whole
 *   matter), the jurisdiction to confirm, a Case step the progression rules
 *   hold for specialist review. Expert Review is a requirement, never a
 *   ticket: nothing here says it was sent.
 * - Checks that can't run now are a technical note, never the Case's status.
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

/** Where the Case stands, in a few words: its lifecycle, then its stage once there is one. */
export function caseState(conversation: Conversation | null): string {
  const status = conversation?.status;
  if (!status || status.lifecycle === null) return LIFECYCLE.in_progress;
  const position = status.position;
  if (status.lifecycle === "in_progress" && position?.stage && position.stageInProgress) return `${position.stage} in progress`;
  return LIFECYCLE[status.lifecycle];
}

const headerButton =
  "inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[0.8125rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05] disabled:cursor-not-allowed disabled:opacity-60";

export function CaseHeader({
  companyId,
  conversation,
  history,
  onNew,
  busy,
}: {
  companyId: string;
  /** Null while the first message of a new chat is on its way (the Case starts with it). */
  conversation: Conversation | null;
  /** The History control (it owns its drawer). */
  history: ReactNode;
  onNew: () => void;
  busy: boolean;
}) {
  const status = conversation?.status ?? null;
  const caseLink = conversation?.case ?? null;
  const title = caseLink?.title ?? conversation?.title ?? "New case";
  const review = status ? expertReviewText(status.attention.expertReview) : null;
  const jurisdiction = status?.attention.jurisdiction === "needs_confirmation";
  const unavailable = status?.checks === "unavailable";
  const held = status?.position?.heldSteps ?? [];
  // The structured record is there once the Case has a workflow (an unclassified Case has none yet).
  const detailsHref =
    caseLink && status?.workflow
      ? `/workspaces/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseLink.id)}`
      : null;
  return (
    <header aria-label="This case" className="border-b border-hero-navy/[0.08] pb-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h1 className="truncate text-[1.0625rem] font-extrabold tracking-[-0.01em] text-hero-navy">{title}</h1>
          <p className="text-[0.8125rem] font-semibold text-hero-muted">{caseState(conversation)}</p>
        </div>
        <div className="-mr-2 flex items-center gap-0.5">
          {detailsHref ? (
            <a className={headerButton} href={detailsHref}>
              <CaseIcon className="size-4" />
              Case details
            </a>
          ) : null}
          {history}
          <button className={headerButton} disabled={busy} onClick={onNew} type="button">
            <PlusIcon className="size-4" />
            New chat
          </button>
        </div>
      </div>
      {review || jurisdiction || held.length > 0 ? (
        <ul aria-label="Needs attention" className="mt-2 flex flex-wrap gap-2">
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
        </ul>
      ) : null}
      {unavailable ? (
        <p className="mt-2 flex items-center gap-1.5 text-[0.8125rem] text-hero-muted" role="note">
          <AlertIcon className="size-3.5 shrink-0" />
          HeroOS&apos;s checks are temporarily unavailable.
        </p>
      ) : null}
    </header>
  );
}
