"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { caseWhen } from "@/components/app/cases-panel";
import { useModalPanel } from "@/components/app/use-modal-panel";
import { iconButton } from "@/components/app/workspace-chrome";
import { CloseIcon, PlusIcon } from "@/components/site/icons";
import { type ConversationList, type ConversationSummary, parseConversationList } from "@/lib/ask/conversation";

/**
 * Ask HeroOS's history (M2-NEW-07): a quiet drawer, never a sidebar that
 * competes with the question. The Company's conversations as the API lists
 * them, most recently active first, a page at a time (its cursor). Each shows
 * a safe title (the Case's, chosen by the server; never a name or a message
 * preview) and when it was last active. Choosing one reopens it.
 */

/** What a conversation is called in the list: its Case's title, else a neutral name. */
export function conversationName(item: Pick<ConversationSummary, "title" | "case">): string {
  return item.case?.title ?? item.title ?? "Conversation";
}

type Load = { kind: "loading" } | { kind: "ready" } | { kind: "failed" };

export function ConversationHistory({
  companyId,
  currentId,
  onChoose,
  onNew,
  onClose,
  returnTo,
  fetcher,
  now = new Date(),
}: {
  companyId: string;
  currentId: string | null;
  onChoose: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
  /** The History button: focus returns there on close. */
  returnTo?: RefObject<HTMLElement | null>;
  fetcher?: typeof fetch;
  now?: Date;
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const panel = useRef<HTMLElement>(null);
  useModalPanel(true, onClose, panel, returnTo);

  /** One page of the list, or null when it couldn't be read. */
  const fetchPage = useCallback(
    async (before: string | null) => {
      const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
      try {
        const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/assistant/conversations${query}`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        });
        return response.status === 200 ? parseConversationList(await response.json().catch(() => null)) : null;
      } catch {
        return null;
      }
    },
    [companyId, fetcher],
  );

  const apply = useCallback((before: string | null, list: ConversationList | null) => {
    if (list === null) {
      setLoad({ kind: "failed" });
      return;
    }
    setItems((current) => (before === null ? list.items : [...current, ...list.items.filter((i) => !current.some((c) => c.id === i.id))]));
    setNext(list.nextBefore);
    setLoad({ kind: "ready" });
  }, []);

  async function page(before: string | null) {
    setLoad({ kind: "loading" });
    apply(before, await fetchPage(before));
  }

  useEffect(() => {
    let live = true;
    void fetchPage(null).then((list) => {
      if (live) apply(null, list);
    });
    return () => {
      live = false;
    };
  }, [fetchPage, apply]);

  return (
    <div className="fixed inset-0 z-40">
      <div aria-hidden="true" className="ws-fade absolute inset-0 bg-hero-navy/20" onClick={onClose} />
      <aside
        aria-labelledby="history-title"
        aria-modal="true"
        className="ws-panel-in absolute inset-x-0 bottom-0 flex max-h-[85%] flex-col rounded-t-[1.75rem] bg-[#fbfaf8] shadow-[0_-20px_60px_-24px_rgb(14_30_61/0.45)] sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[24rem] sm:rounded-none sm:rounded-l-[1.75rem]"
        ref={panel}
        role="dialog"
        tabIndex={-1}
      >
        <div className="flex h-16 shrink-0 items-center justify-between pl-5 pr-2">
          <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="history-title">
            Recent conversations
          </h2>
          <button aria-label="Close recent conversations" className={iconButton} onClick={onClose} type="button">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="px-3">
          <button
            className="flex min-h-11 w-full items-center gap-2 rounded-xl border border-hero-border bg-white px-3.5 text-left text-[0.9375rem] font-semibold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] transition-colors duration-150 hover:bg-hero-blue-tint"
            data-autofocus
            onClick={onNew}
            type="button"
          >
            <PlusIcon className="size-5" />
            New conversation
          </button>
        </div>
        <nav aria-label="Your conversations" className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 pb-5">
          {load.kind === "ready" && items.length === 0 ? (
            <p className="px-4 text-[0.9375rem] text-hero-muted">No conversations yet. Ask HeroOS about an HR situation to start one.</p>
          ) : null}
          {items.length > 0 ? (
            <ul className="space-y-0.5 px-1">
              {items.map((item) => {
                const current = item.id === currentId;
                return (
                  <li key={item.id}>
                    <button
                      aria-current={current ? "true" : undefined}
                      className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-[current=true]:bg-hero-blue-tint/70"
                      onClick={() => onChoose(item.id)}
                      type="button"
                    >
                      <span className="truncate text-[0.9375rem] font-semibold text-hero-navy">{conversationName(item)}</span>
                      <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[0.8125rem] text-hero-muted">
                        <span className="truncate">{item.case ? "Case" : "No case"}</span>
                        <span aria-hidden="true">·</span>
                        <time className="shrink-0 tabular-nums" dateTime={item.updatedAt}>
                          {caseWhen(item.updatedAt, now)}
                        </time>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {load.kind === "loading" ? (
            <p className="px-4 py-2 text-[0.9375rem] text-hero-muted" role="status">
              Loading conversations…
            </p>
          ) : null}
          {load.kind === "failed" ? (
            <p className="px-4 py-2 text-[0.9375rem] text-hero-navy" role="alert">
              HeroOS couldn&apos;t load your conversations.{" "}
              <button className="font-bold text-hero-blue-ink underline" onClick={() => void page(items.length > 0 ? next : null)} type="button">
                Try again
              </button>
            </p>
          ) : null}
          {load.kind === "ready" && next !== null ? (
            <div className="px-3 pt-2">
              <button
                className="min-h-11 w-full rounded-xl px-3 text-[0.9375rem] font-bold text-hero-blue-ink hover:bg-hero-navy/[0.05]"
                onClick={() => void page(next)}
                type="button"
              >
                Show older conversations
              </button>
            </div>
          ) : null}
        </nav>
      </aside>
    </div>
  );
}
