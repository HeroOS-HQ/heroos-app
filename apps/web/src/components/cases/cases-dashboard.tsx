import { ArrowLeftIcon, ArrowRightIcon, CaseIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary, buttonQuiet, card, lede, pageTitle } from "@/components/ui/styles";
import { caseStatusTone, formatDay } from "@/lib/workflows/copy";
import type { CaseSummary } from "@/lib/workflows/model";

export const casesHref = (companyId: string) => `/workspaces/${encodeURIComponent(companyId)}/cases`;
export const caseHref = (companyId: string, caseId: string) =>
  `${casesHref(companyId)}/${encodeURIComponent(caseId)}`;

/** What this first version does, and doesn't, so nothing suggests more. */
export function SliceNotice({ className }: { className?: string }) {
  return (
    <Notice className={className} title="Early version: initial facts only">
      HeroOS guides you through structured questions and saves your answers. Conditions and safeguard checks, legal
      assessment, documents and expert review aren&apos;t available yet, and nothing you enter is assessed or decided.
    </Notice>
  );
}

/**
 * CASES_READY: the Company's Disciplinary Cases, most recently active first.
 * Only an administrator sees "New case" (the API enforces it on create).
 */
export function CasesDashboard({
  companyId,
  companyName,
  canCreate,
  cases,
}: {
  companyId: string;
  companyName: string;
  canCreate: boolean;
  cases: CaseSummary[];
}) {
  const newHref = `${casesHref(companyId)}/new`;
  return (
    <div className="mx-auto flex w-full max-w-[60rem] flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      <div>
        <a className={buttonQuiet} href={`/workspaces/${encodeURIComponent(companyId)}`}>
          <ArrowLeftIcon className="size-4" />
          {companyName}
        </a>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">HR workflow</p>
            <h1 className={`${pageTitle} mt-2`}>Disciplinary cases</h1>
          </div>
          {canCreate ? (
            <a className={`${buttonPrimary} min-h-11 px-6 text-[0.9375rem]`} href={newHref}>
              New case
            </a>
          ) : null}
        </div>
        <p className={`mt-3 max-w-[42rem] ${lede}`}>
          A guided way to record a conduct concern step by step. Each case keeps its answers, so you can stop and come
          back at any time.
        </p>
      </div>

      <SliceNotice />

      {cases.length === 0 ? (
        <section aria-labelledby="empty-heading" className={`${card} flex flex-col items-start gap-3 p-6 sm:p-8`}>
          <span className="inline-flex size-11 items-center justify-center rounded-xl bg-hero-blue-tint text-hero-blue">
            <CaseIcon className="size-5" />
          </span>
          <h2 className="text-lg font-extrabold text-hero-navy" id="empty-heading">
            No Disciplinary cases yet
          </h2>
          <p className="max-w-[36rem] text-[0.9375rem] leading-relaxed text-hero-muted">
            {canCreate
              ? "Start a case when a conduct concern comes up. You'll answer a few questions about what happened; you can fill in the rest later."
              : "Only company administrators can start a case. Cases they create will appear here."}
          </p>
          {canCreate ? (
            <a className={`${buttonPrimary} mt-1 min-h-11 px-6 text-[0.9375rem]`} href={newHref}>
              Start a case
            </a>
          ) : null}
        </section>
      ) : (
        <section aria-labelledby="list-heading" className={`${card} p-2 sm:p-3`}>
          <h2 className="sr-only" id="list-heading">
            All cases
          </h2>
          <ul aria-label="Disciplinary cases" className="flex flex-col">
            {cases.map((item) => (
              <li className="border-b border-hero-border last:border-b-0" key={item.id}>
                <a
                  className="group flex flex-col gap-2 rounded-2xl px-4 py-4 transition-colors duration-150 hover:bg-hero-blue-tint/60 focus-visible:outline-3 focus-visible:outline-offset-[-3px] focus-visible:outline-hero-blue sm:flex-row sm:items-center sm:gap-4 sm:px-5"
                  href={caseHref(companyId, item.id)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block break-words text-base font-bold text-hero-navy">{item.title}</span>
                    <span className="mt-1 block text-sm text-hero-muted">
                      {item.answered} of {item.total} initial questions answered · Last updated{" "}
                      <time dateTime={item.updatedAt}>{formatDay(item.updatedAt)}</time>
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    <StatusBadge tone={caseStatusTone(item.status.code)}>{item.status.label}</StatusBadge>
                    <ArrowRightIcon className="size-4 text-hero-muted transition-transform duration-150 group-hover:translate-x-0.5" />
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!canCreate && cases.length > 0 ? (
        <p className="text-sm text-hero-muted">You can view these cases. Only company administrators can create or update them.</p>
      ) : null}
    </div>
  );
}
