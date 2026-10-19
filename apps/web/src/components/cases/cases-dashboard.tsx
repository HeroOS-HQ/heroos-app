import { ArrowRightIcon, BookIcon, CaseIcon, LightbulbIcon, PlusIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import { JurisdictionBanner } from "@/components/workspace/jurisdiction-banner";
import { PageBanner, pageGutter } from "@/components/workspace/page-banner";
import type { Blueprint } from "@/lib/server/heroos-api";
import type { CaseSummary } from "@/lib/workflows/model";

import { CasesTable } from "./cases-table";

export const casesHref = (companyId: string) => `/workspaces/${encodeURIComponent(companyId)}/cases`;
export const caseHref = (companyId: string, caseId: string) =>
  `${casesHref(companyId)}/${encodeURIComponent(caseId)}`;

/** What this version does, and doesn't, so nothing suggests more. */
export function SliceNotice({ className }: { className?: string }) {
  return (
    <Notice className={className} title="What this version does">
      HeroOS guides the intake: structured questions, the case&apos;s jurisdiction and a safety screening, with fixed
      checks that can pause a case for specialist advice. Next steps, your decision records and document previews
      appear where approved rules and templates are installed. HeroOS never decides an outcome, and documents are
      previews only, never issued.
    </Notice>
  );
}

/** The breadcrumb levels above a Disciplinary page. */
export const disciplinaryCrumbs = (companyId: string) => [
  { label: "HR Services", href: `/workspaces/${encodeURIComponent(companyId)}/hr-services` },
  { label: "Conduct & Discipline", href: `/workspaces/${encodeURIComponent(companyId)}/disciplinary` },
];

/**
 * CASES_READY (JJ design review, screen 09): the Company's Disciplinary Cases,
 * most recently active first. Rendered for Company administrators only (the
 * API enforces it on every request; members see AdminOnlyView instead).
 */
export function CasesDashboard({
  companyId,
  cases,
  blueprint = null,
}: {
  companyId: string;
  cases: CaseSummary[];
  /** The Company profile, for its jurisdiction readiness (null against an API without profiles). */
  blueprint?: Blueprint | null;
}) {
  const newHref = `${casesHref(companyId)}/new`;
  return (
    <>
      <PageBanner
        breadcrumbs={[...disciplinaryCrumbs(companyId), { label: "Cases" }]}
        bubble="Keep track of your cases easily!"
        title="Conduct & Discipline – Cases"
      >
        <p className="max-w-[40rem]">
          View and manage your company&apos;s disciplinary cases. Start a new case, or continue one where you left off;
          each case keeps its answers.
        </p>
      </PageBanner>

      <div className={`${pageGutter} flex flex-col gap-4 pb-10`}>
        <JurisdictionBanner blueprint={blueprint} companyId={companyId} variant="cases" />

        <section aria-labelledby="list-heading" className="rounded-[1.25rem] border border-hero-border bg-white p-4 shadow-hero-card sm:p-5">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-[1.75rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy" id="list-heading">
                Cases
              </h2>
              <p className="mt-1 text-base text-hero-muted">All disciplinary cases for your company.</p>
            </div>
            <a className={`${buttonPrimary} min-h-12 rounded-xl px-5 text-[0.9375rem]`} href={newHref}>
              <PlusIcon className="size-5" />
              Create a new case
              <ArrowRightIcon className="size-4" />
            </a>
          </div>
          <CasesTable
            cases={cases}
            companyId={companyId}
            empty={
              <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-hero-control/60 p-6 sm:p-8">
                <span className="inline-flex size-11 items-center justify-center rounded-xl bg-hero-blue-tint text-hero-blue">
                  <CaseIcon className="size-5" />
                </span>
                <h3 className="text-lg font-extrabold text-hero-navy">No Disciplinary cases yet</h3>
                <p className="max-w-[36rem] text-[0.9375rem] leading-relaxed text-hero-muted">
                  Start a case when a conduct concern comes up. You&apos;ll answer a few questions about what happened;
                  you can fill in the rest later.
                </p>
                <a className={`${buttonPrimary} mt-1 min-h-11 rounded-xl px-6 text-[0.9375rem]`} href={newHref}>
                  Start a case
                </a>
              </div>
            }
          />
        </section>

        <div className="grid gap-4 lg:grid-cols-2">
          <section aria-labelledby="help-heading" className="flex gap-4 rounded-[1.25rem] border border-[#dde6f4] bg-[#f4f7fc] p-5">
            <BookIcon className="size-8 shrink-0 text-hero-navy" />
            <div>
              <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id="help-heading">
                Need help with a case?
              </h2>
              <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
                See how the Conduct &amp; Discipline workflow works and what HeroOS does at each step.
              </p>
              <a
                className={`${buttonSecondary} mt-3 min-h-11 rounded-xl px-4 text-[0.9375rem]`}
                href={`/workspaces/${encodeURIComponent(companyId)}/disciplinary`}
              >
                How it works
                <ArrowRightIcon className="size-4" />
              </a>
            </div>
          </section>
          <section aria-labelledby="reminder-heading" className="flex gap-4 rounded-[1.25rem] border border-[#dde6f4] bg-[#f4f7fc] p-5">
            <LightbulbIcon className="size-8 shrink-0 text-hero-blue" />
            <div>
              <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id="reminder-heading">
                Important reminder
              </h2>
              <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
                Follow your company&apos;s policies and the employment law that applies to it; some cases need specialist
                advice. Disciplinary cases are confidential: only your company&apos;s administrators can see them.
              </p>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
