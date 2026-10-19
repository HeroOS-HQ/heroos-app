"use client";

import { type ReactNode, useId, useMemo, useState } from "react";

import { ArrowRightIcon, SearchIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { caseStatusTone, formatDay } from "@/lib/workflows/copy";
import type { CaseSummary } from "@/lib/workflows/model";

const caseLink = (companyId: string, caseId: string) =>
  `/workspaces/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}`;

/** The first block of the Case's id: enough to tell cases apart and to search by. */
export const shortId = (id: string) => id.slice(0, 8).toUpperCase();

/** The statuses the listed cases actually have (the API's codes and words), in first-seen order. */
export function caseStatuses(cases: CaseSummary[]): { code: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const item of cases) if (!seen.has(item.status.code)) seen.set(item.status.code, item.status.label);
  return [...seen].map(([code, label]) => ({ code, label }));
}

/** Cases whose title or id contains the search, with the chosen status ("" for any). */
export function filterCases(cases: CaseSummary[], query: string, status: string): CaseSummary[] {
  const needle = query.trim().toLowerCase();
  return cases.filter(
    (item) =>
      (status === "" || item.status.code === status) &&
      (needle === "" || item.title.toLowerCase().includes(needle) || item.id.toLowerCase().includes(needle)),
  );
}

const cell = "border-t border-hero-border px-4 py-2 align-middle max-md:border-0 max-md:p-0";
const head = "bg-[#f3f6fb] px-4 py-2.5 text-left text-sm font-bold text-hero-navy";

/**
 * A Company's Disciplinary Cases as a table (cards on phones): the API's
 * titles, statuses and dates only. With `controls`, a search by title or id
 * and a filter by the statuses present; both work on the list the page
 * received and never request anything.
 */
export function CasesTable({
  companyId,
  cases,
  controls = true,
  limit,
  empty,
}: {
  companyId: string;
  cases: CaseSummary[];
  controls?: boolean;
  /** Show only the first cases (the list is most recently active first). */
  limit?: number;
  /** Shown instead of the table when there are no cases at all. */
  empty: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const searchId = useId();
  const statusId = useId();
  const statuses = useMemo(() => caseStatuses(cases), [cases]);
  const filtered = controls ? filterCases(cases, query, status) : cases;
  const shown = limit === undefined ? filtered : filtered.slice(0, limit);
  const filtering = query.trim() !== "" || status !== "";

  if (cases.length === 0) return <>{empty}</>;

  const clear = () => {
    setQuery("");
    setStatus("");
  };

  return (
    <div className="flex flex-col gap-4">
      {controls ? (
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <div className="relative min-w-0 flex-1 md:max-w-[25rem]">
            <label className="sr-only" htmlFor={searchId}>
              Search cases by title or ID
            </label>
            <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-hero-muted" />
            <input
              autoComplete="off"
              className="block min-h-11 w-full rounded-xl border border-hero-control bg-white py-2 pl-11 pr-4 text-[0.9375rem] text-hero-navy placeholder:text-hero-muted focus:border-hero-blue"
              id={searchId}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by case title or ID…"
              type="search"
              value={query}
            />
          </div>
          <div className="md:w-[14rem]">
            <label className="sr-only" htmlFor={statusId}>
              Status
            </label>
            <select
              className="block min-h-11 w-full rounded-xl border border-hero-control bg-white px-3.5 text-[0.9375rem] font-semibold text-hero-navy focus:border-hero-blue"
              id={statusId}
              onChange={(event) => setStatus(event.target.value)}
              value={status}
            >
              <option value="">All statuses</option>
              {statuses.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          {filtering ? (
            <button
              className="inline-flex min-h-11 items-center self-start rounded-lg px-1 text-[0.9375rem] font-bold text-hero-blue-ink underline underline-offset-4 md:ml-auto md:self-center"
              onClick={clear}
              type="button"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      ) : null}

      {shown.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-hero-control/60 px-5 py-8 text-center">
          <p className="font-bold text-hero-navy">No cases match your search.</p>
          <p className="mt-1 text-[0.9375rem] text-hero-muted">Try another title or ID, or show all statuses.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-hero-border max-md:overflow-visible max-md:rounded-none max-md:border-0">
          <table className="w-full border-collapse text-left max-md:block">
            <thead className="max-md:hidden">
              <tr>
                <th className={head} scope="col">
                  Case
                </th>
                <th className={head} scope="col">
                  Status
                </th>
                <th className={`${head} max-lg:hidden`} scope="col">
                  Intake
                </th>
                <th className={`${head} max-xl:hidden`} scope="col">
                  Created
                </th>
                <th className={head} scope="col">
                  Last updated
                </th>
                <th className={head} scope="col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody className="max-md:flex max-md:flex-col max-md:gap-3">
              {shown.map((item) => (
                <tr
                  className="transition-colors duration-150 hover:bg-hero-blue-tint/40 max-md:flex max-md:flex-col max-md:gap-2.5 max-md:rounded-2xl max-md:border max-md:border-hero-border max-md:bg-white max-md:p-4"
                  key={item.id}
                >
                  <td className={`${cell} min-w-0`}>
                    <span className="block break-words text-[0.9375rem] font-bold text-hero-navy">{item.title}</span>
                    <span className="block text-xs font-semibold tracking-wide text-hero-muted">ID {shortId(item.id)}</span>
                  </td>
                  <td className={cell}>
                    <StatusBadge tone={caseStatusTone(item.status.code)} wrap>
                      {item.status.label}
                    </StatusBadge>
                  </td>
                  <td className={`${cell} text-[0.9375rem] text-hero-navy md:max-lg:hidden`}>
                    <span className="md:hidden">Intake: </span>
                    {item.answered} of {item.total} answered
                  </td>
                  <td className={`${cell} whitespace-nowrap text-[0.9375rem] text-hero-navy max-xl:hidden`}>
                    <time dateTime={item.createdAt}>{formatDay(item.createdAt)}</time>
                  </td>
                  <td className={`${cell} whitespace-nowrap text-[0.9375rem] text-hero-navy`}>
                    <span className="md:hidden">Last updated </span>
                    <time dateTime={item.updatedAt}>{formatDay(item.updatedAt)}</time>
                  </td>
                  <td className={`${cell} text-right max-md:text-left`}>
                    <a
                      className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-hero-control bg-white px-4 text-sm font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint max-md:w-full"
                      href={caseLink(companyId, item.id)}
                    >
                      View{" "}
                      <span className="sr-only">case: {item.title}</span>
                      <ArrowRightIcon className="size-4" />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {controls ? (
        <p aria-live="polite" className="text-sm text-hero-muted" role="status">
          {filtering
            ? `Showing ${shown.length} of ${cases.length} ${cases.length === 1 ? "case" : "cases"}`
            : `${cases.length} ${cases.length === 1 ? "case" : "cases"}`}
        </p>
      ) : null}
    </div>
  );
}
