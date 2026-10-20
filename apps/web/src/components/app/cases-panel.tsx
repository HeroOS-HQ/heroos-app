"use client";

import { type RefObject, useRef, useState } from "react";

import { CloseIcon, PlusIcon, SearchIcon } from "@/components/site/icons";
import { caseStatusDot } from "@/lib/workflows/copy";
import type { CaseSummary } from "@/lib/workflows/model";

import { useModalPanel } from "./use-modal-panel";
import { iconButton } from "./workspace-chrome";

/**
 * The Cases drawer (approved design, Page 1): a quiet utility, never a fourth
 * page. New question, a search, and the Company's cases as the API lists them
 * (title, status in words, last update), today's first. Rendered only once
 * open, in the browser, so "today" and the times are the viewer's own.
 */

const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const DAY_YEAR = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** "09:12" today, "16 Oct" this year, "16 Oct 2025" before. */
export function caseWhen(iso: string, now: Date): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  if (sameDay(at, now)) return TIME.format(at);
  return at.getFullYear() === now.getFullYear() ? DAY.format(at) : DAY_YEAR.format(at);
}

/** Today's cases, then the rest; newest first in each (the API's order is kept otherwise). */
export function groupCases(cases: CaseSummary[], now: Date): { label: "Today" | "Earlier"; cases: CaseSummary[] }[] {
  const sorted = [...cases].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  const today = sorted.filter((item) => sameDay(new Date(item.updatedAt), now));
  const earlier = sorted.filter((item) => !sameDay(new Date(item.updatedAt), now));
  return [
    { label: "Today" as const, cases: today },
    { label: "Earlier" as const, cases: earlier },
  ].filter((group) => group.cases.length > 0);
}

export function CasesPanel({
  companyId,
  cases,
  currentCaseId,
  onClose,
  returnTo,
  now = new Date(),
}: {
  companyId: string;
  cases: CaseSummary[];
  currentCaseId?: string;
  onClose: () => void;
  /** The Cases button: focus returns there on close. */
  returnTo?: RefObject<HTMLElement | null>;
  now?: Date;
}) {
  const [query, setQuery] = useState("");
  const panel = useRef<HTMLElement>(null);
  useModalPanel(true, onClose, panel, returnTo);

  const base = `/workspaces/${encodeURIComponent(companyId)}`;
  const search = query.trim().toLowerCase();
  const listed = search === "" ? cases : cases.filter((item) => item.title.toLowerCase().includes(search));
  const groups = groupCases(listed, now);

  return (
    <div className="fixed inset-0 z-40">
      <div aria-hidden="true" className="ws-fade absolute inset-0 bg-hero-navy/20" onClick={onClose} />
      <aside
        aria-labelledby="cases-title"
        aria-modal="true"
        className="ws-from-left absolute inset-y-0 left-0 flex w-[min(21rem,88vw)] flex-col border-r border-hero-border bg-[#fbfaf8] shadow-[24px_0_60px_-28px_rgb(14_30_61/0.45)]"
        ref={panel}
        role="dialog"
        tabIndex={-1}
      >
        <div className="flex h-16 shrink-0 items-center justify-between pl-5 pr-2">
          <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="cases-title">
            Cases
          </h2>
          <button aria-label="Close cases" className={iconButton} onClick={onClose} type="button">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="space-y-2.5 px-3">
          <a
            className="flex min-h-11 items-center gap-2 rounded-xl border border-hero-border bg-white px-3.5 text-[0.9375rem] font-semibold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] transition-colors duration-150 hover:bg-hero-blue-tint"
            data-autofocus
            href={base}
          >
            <PlusIcon className="size-5" />
            New question
          </a>
          <label className="flex min-h-11 items-center gap-2 rounded-xl border border-hero-border bg-white px-3 text-[0.9375rem] text-hero-navy focus-within:border-hero-blue">
            <SearchIcon className="size-4 shrink-0 text-hero-muted" />
            <span className="sr-only">Search your cases</span>
            <input
              autoComplete="off"
              className="min-w-0 flex-1 bg-transparent placeholder:text-hero-muted focus-visible:outline-none"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search cases"
              type="search"
              value={query}
            />
          </label>
        </div>
        <nav aria-label="Your cases" className="mt-5 min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-1 pb-5">
          {cases.length === 0 ? (
            <p className="px-4 text-[0.9375rem] text-hero-muted">No cases yet. Ask HeroOS about an HR situation to open one.</p>
          ) : groups.length === 0 ? (
            <p className="px-4 text-[0.9375rem] text-hero-muted">No cases match “{query.trim()}”.</p>
          ) : null}
          {groups.map((group) => (
            <div key={group.label}>
              <h3 className="px-4 text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">{group.label}</h3>
              <ul className="mt-1.5 space-y-0.5 px-1">
                {group.cases.map((item) => {
                  const current = item.id === currentCaseId;
                  return (
                    <li key={item.id}>
                      <a
                        aria-current={current ? "page" : undefined}
                        className="flex flex-col rounded-xl px-3 py-2.5 transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-[current=page]:bg-hero-blue-tint/70"
                        href={`${base}/cases/${encodeURIComponent(item.id)}`}
                      >
                        <span className="truncate text-[0.9375rem] font-semibold text-hero-navy">{item.title}</span>
                        <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[0.8125rem] text-hero-muted">
                          <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${caseStatusDot(item.status.code)}`} />
                          <span className="truncate">{item.status.label}</span>
                          <span aria-hidden="true">·</span>
                          <time className="shrink-0 tabular-nums" dateTime={item.updatedAt}>
                            {caseWhen(item.updatedAt, now)}
                          </time>
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </div>
  );
}
