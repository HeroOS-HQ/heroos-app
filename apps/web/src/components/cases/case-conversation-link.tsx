"use client";

import { useSyncExternalStore } from "react";

import { caseWhen } from "@/components/app/cases-panel";
import { AdviserMark } from "@/components/app/workspace-chrome";
import { ChevronRightIcon } from "@/components/site/icons";
import type { ConversationSummary } from "@/lib/ask/conversation";

/**
 * "Continue with HeroOS" (M2-NEW-08): the Case is chat-first. Its Ask HeroOS
 * conversation (M2-NEW-07) is where the founder carries on in their own words,
 * HeroOS asks what it needs one question at a time, and the Case's formal
 * steps appear inline. This page is the case's record and details. A Case
 * opened another way has no conversation yet: Ask HeroOS is still where to
 * talk to HeroOS.
 */
export function CaseConversationLink({
  companyId,
  conversation,
  canEdit = true,
}: {
  companyId: string;
  conversation: ConversationSummary | null;
  /** Ask HeroOS is for company administrators. */
  canEdit?: boolean;
}) {
  // The time is the viewer's own: shown only in the browser (no server/client mismatch).
  const inBrowser = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );
  if (!canEdit) return null;
  const now = inBrowser ? new Date() : null;
  const ask = `/workspaces/${encodeURIComponent(companyId)}`;
  const href = conversation ? `${ask}?conversation=${encodeURIComponent(conversation.id)}` : ask;
  return (
    <section aria-labelledby="ask-conversation-heading" className="mb-2">
      <a
        className="group flex min-h-16 items-center gap-3 rounded-2xl border border-hero-blue/40 bg-white px-4 py-3.5 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_16px_36px_-28px_rgb(14_30_61/0.45)] transition-colors duration-150 hover:bg-hero-blue-tint/50"
        href={href}
      >
        <AdviserMark />
        <span className="min-w-0 flex-1">
          <span className="block text-[0.9375rem] font-extrabold text-hero-navy" id="ask-conversation-heading">
            {conversation ? "Continue with HeroOS" : "Ask HeroOS"}
          </span>
          <span className="block text-[0.8125rem] text-hero-muted">
            {conversation ? (
              <>
                Carry on in your own words: HeroOS asks what it needs and shows your next steps
                {now ? (
                  <>
                    {" "}
                    · last message <time dateTime={conversation.updatedAt}>{caseWhen(conversation.updatedAt, now)}</time>
                  </>
                ) : null}
              </>
            ) : (
              "This case was opened without a conversation. Ask HeroOS anything about it in your own words."
            )}
          </span>
        </span>
        <ChevronRightIcon className="size-5 shrink-0 text-hero-muted transition-transform duration-150 group-hover:translate-x-0.5" />
      </a>
    </section>
  );
}
