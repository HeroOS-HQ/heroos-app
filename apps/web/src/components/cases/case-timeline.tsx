"use client";

import { useState } from "react";

import { AlertIcon, CheckIcon, ClockIcon, PencilIcon, ShieldIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonSecondary } from "@/components/ui/styles";
import { formatDayTime } from "@/lib/workflows/copy";
import { isTimelinePage, NATURE_COPY, STATUS_COPY, type TimelineEntry, type TimelinePage } from "@/lib/workflows/decisions";

/**
 * The unified case history (M2-04), newest first: the Case's creation, saved
 * answers, HeroOS's checks, workflow steps, refused requests and employer
 * records, composed by the API from the stored records. Every entry says in
 * words what kind of thing it is, so an employer record or a refused request
 * is never mistaken for a completed workflow step. Older entries load a page
 * at a time; a new view from the API (after any write) starts over.
 */

function Marker({ entry }: { entry: TimelineEntry }) {
  if (entry.nature === "refused_request") return <AlertIcon className="size-4 text-hero-navy" />;
  if (entry.status === "specialist_review" || entry.status === "on_hold") return <ShieldIcon className="size-4 text-hero-danger" />;
  if (entry.nature === "employer_record") return <PencilIcon className="size-4 text-hero-blue-ink" />;
  if (entry.nature === "workflow_change") return <CheckIcon className="size-4 text-hero-success" />;
  return <ClockIcon className="size-4 text-hero-muted" />;
}

function Entry({ entry }: { entry: TimelineEntry }) {
  const nature = NATURE_COPY[entry.nature];
  const status = entry.status === null ? null : STATUS_COPY[entry.status];
  return (
    <li className="relative flex gap-3 border-b border-hero-border py-3.5 last:border-b-0" data-entry={entry.id}>
      <span aria-hidden="true" className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-hero-border bg-white">
        <Marker entry={entry} />
      </span>
      <div className="min-w-0 flex-1">
        <p className={`text-[0.9375rem] font-semibold leading-snug ${entry.status === "superseded" ? "text-hero-navy/70" : "text-hero-navy"}`}>
          {entry.title}
        </p>
        <p className="mt-1 flex flex-wrap gap-1.5">
          <StatusBadge tone={nature.tone}>{nature.label}</StatusBadge>
          {status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
        </p>
        {entry.detail ? <p className="mt-1.5 break-words text-sm leading-relaxed text-hero-navy/80">{entry.detail}</p> : null}
        <p className="mt-1 text-xs text-hero-muted">
          <time dateTime={entry.at}>{formatDayTime(entry.at)}</time>
          {entry.byViewer === true ? " · You" : entry.byViewer === false ? " · Another administrator" : ""}
        </p>
      </div>
    </li>
  );
}

export function CaseTimeline({
  companyId,
  caseId,
  page,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  page: TimelinePage;
  fetcher?: typeof fetch;
}) {
  const [state, setState] = useState({ base: page, older: [] as TimelineEntry[], next: page.nextBefore });
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  // A new first page from the API (after any write) replaces what was loaded.
  if (state.base !== page) setState({ base: page, older: [], next: page.nextBefore });
  const entries = [...page.entries, ...(state.base === page ? state.older : [])];
  const next = state.base === page ? state.next : page.nextBefore;

  async function loadOlder() {
    if (loading || next === null) return;
    setLoading(true);
    setFailed(false);
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/history?before=${encodeURIComponent(next)}`,
        { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", redirect: "error" },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isTimelinePage(body.page)) {
        const older = body.page;
        setState((current) => ({ ...current, older: [...current.older, ...older.entries], next: older.nextBefore }));
      } else {
        setFailed(true);
      }
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <p className="mt-2 text-sm leading-relaxed text-hero-muted">
        Most recent first. <strong className="font-semibold text-hero-navy">Employer record</strong>: entered by your company,
        not verified by HeroOS. <strong className="font-semibold text-hero-navy">HeroOS check</strong>: the result of fixed
        checks. <strong className="font-semibold text-hero-navy">Workflow step</strong>: recorded in the workflow.{" "}
        <strong className="font-semibold text-hero-navy">Not allowed</strong>: a request that was refused, so nothing changed.
      </p>
      <ol className="mt-3 flex flex-col">
        {entries.map((entry) => (
          <Entry entry={entry} key={entry.id} />
        ))}
      </ol>
      <p className="mt-2 text-sm text-hero-muted" role="status">
        Showing {entries.length} of {page.total} {page.total === 1 ? "entry" : "entries"}.
      </p>
      {failed ? (
        <Notice className="mt-3" title="Older entries couldn't be loaded" tone="caution">
          Try again, or reload the case.
        </Notice>
      ) : null}
      {next !== null ? (
        <button className={`${buttonSecondary} mt-3`} disabled={loading} onClick={() => void loadOlder()} type="button">
          {loading ? "Loading…" : "Show older entries"}
        </button>
      ) : null}
    </div>
  );
}
