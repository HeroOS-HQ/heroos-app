"use client";

import { useSyncExternalStore } from "react";

import { caseWhen } from "@/components/app/cases-panel";
import { AdviserMark } from "@/components/app/workspace-chrome";
import { ChevronRightIcon } from "@/components/site/icons";
import type { ConversationSummary } from "@/lib/ask/conversation";

/**
 * The Ask HeroOS conversation this Case started from (M2-NEW-07): a link to the
 * actual chat, where it can be read and continued. It stays a conversation,
 * not part of the Case's record: the guided workflow below and "Decisions &
 * history" are the Case's own.
 */
export function CaseConversationLink({ companyId, conversation }: { companyId: string; conversation: ConversationSummary }) {
  // The time is the viewer's own: shown only in the browser (no server/client mismatch).
  const inBrowser = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );
  const now = inBrowser ? new Date() : null;
  const href = `/workspaces/${encodeURIComponent(companyId)}?conversation=${encodeURIComponent(conversation.id)}`;
  return (
    <section aria-labelledby="ask-conversation-heading" className="mb-8">
      <a
        className="group flex min-h-16 items-center gap-3 rounded-2xl border border-hero-navy/[0.1] bg-white px-4 py-3 shadow-[0_1px_2px_rgb(14_30_61/0.04)] transition-colors duration-150 hover:bg-hero-blue-tint/50"
        href={href}
      >
        <AdviserMark />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9375rem] font-extrabold text-hero-navy" id="ask-conversation-heading">
            Your Ask HeroOS conversation
          </span>
          <span className="block text-[0.8125rem] text-hero-muted">
            This case started there. Read it and carry on
            {now ? (
              <>
                {" "}
                · last message <time dateTime={conversation.updatedAt}>{caseWhen(conversation.updatedAt, now)}</time>
              </>
            ) : null}
          </span>
        </span>
        <ChevronRightIcon className="size-5 shrink-0 text-hero-muted transition-transform duration-150 group-hover:translate-x-0.5" />
      </a>
    </section>
  );
}
