import type { ReactNode } from "react";

import { casesHref } from "@/components/cases/cases-dashboard";
import { CasesTable } from "@/components/cases/cases-table";
import {
  ArrowRightIcon,
  BookIcon,
  CheckIcon,
  ChevronRightIcon,
  ClockIcon,
  DocumentIcon,
  LockIcon,
  PlusIcon,
  ShieldIcon,
} from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary } from "@/components/ui/styles";
import type { WorkspaceDetails } from "@/lib/server/heroos-api";
import type { Tone } from "@/lib/workflows/copy";
import type { CaseSummary } from "@/lib/workflows/model";

import { JurisdictionBanner } from "./jurisdiction-banner";
import { PageBanner, pageGutter } from "./page-banner";
import { jurisdictionConfirmed } from "./workflow-areas";

type Point = { title: string; detail: string };

/** How the product works today: its own behaviour, never a legal procedure or a pathway's stages. */
const GUIDED: Point[] = [
  { title: "Start a case", detail: "A short, neutral title; no employee names." },
  { title: "Guided intake", detail: "Fixed questions, the jurisdiction and a safety screening." },
  { title: "Checks and holds", detail: "Fixed checks can pause a case for specialist advice." },
  { title: "Next steps", detail: "Only where approved rules and templates are installed." },
];

const YOURS: Point[] = [
  { title: "Choosing the pathway", detail: "You choose it; HeroOS doesn't classify the matter." },
  { title: "Your decisions", detail: "Recorded by you, with corrections kept in the history." },
  { title: "Specialist advice", detail: "When a case is held, get qualified advice first." },
  { title: "Hannah AI demo", detail: "Exploratory, fictional examples; never changes the case." },
];

function Points({ points, tone }: { points: Point[]; tone: "blue" | "yellow" }) {
  return (
    <ol className="mt-4 flex flex-col gap-3">
      {points.map((point, index) => (
        <li className="flex gap-3" key={point.title}>
          <span
            aria-hidden="true"
            className={`inline-flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-extrabold ${
              tone === "blue" ? "bg-hero-light-blue text-white" : "bg-hero-yellow text-hero-navy"
            }`}
          >
            {index + 1}
          </span>
          <span>
            <span className="block text-base font-bold text-hero-navy">{point.title}</span>
            <span className="block text-sm leading-snug text-hero-muted">{point.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function AvailabilityRow({
  icon,
  title,
  detail,
  status,
  tone,
}: {
  icon: ReactNode;
  title: string;
  detail?: string;
  status: string;
  tone: Tone;
}) {
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 py-2.5">
      {icon}
      <span className="text-sm font-bold text-hero-navy">{title}</span>
      <StatusBadge tone={tone}>{status}</StatusBadge>
      {detail ? <span className="col-span-2 col-start-2 text-sm leading-snug text-hero-muted">{detail}</span> : null}
    </li>
  );
}

const roundIcon = (tone: "positive" | "caution" | "muted", child: ReactNode) => (
  <span
    aria-hidden="true"
    className={`inline-flex size-8 shrink-0 items-center justify-center rounded-full ${
      tone === "positive" ? "bg-hero-success text-white" : tone === "caution" ? "bg-hero-yellow text-hero-navy" : "bg-hero-bg text-hero-muted"
    }`}
  >
    {child}
  </span>
);

/**
 * Conduct & Discipline (JJ design review, screen 08), for a Company
 * administrator: what the workflow does today, what waits for the Company's
 * jurisdiction, and the Company's most recent cases. The pathways and stages
 * in the review mockup are illustrative and not approved, so they are not
 * shown; this page describes the product's own behaviour only.
 */
export function DisciplineOverview({ details, cases }: { details: WorkspaceDetails; cases: CaseSummary[] }) {
  const { company, blueprint } = details;
  const confirmed = jurisdictionConfirmed(blueprint);
  const base = `/workspaces/${encodeURIComponent(company.id)}`;
  const listHref = casesHref(company.id);

  return (
    <>
      <PageBanner
        breadcrumbs={[{ label: "HR Services", href: `${base}/hr-services` }, { label: "Conduct & Discipline" }]}
        bubble="Let's handle conduct concerns carefully, one step at a time."
        title="Conduct & Discipline"
      >
        <p className="max-w-[44rem]">
          A guided workflow to help you record and handle employee conduct concerns fairly and consistently. Your
          answers, decisions and history stay together in one confidential case.
        </p>
      </PageBanner>

      <div className={`${pageGutter} grid gap-4 pb-10 xl:grid-cols-[minmax(0,1fr)_22.5rem] xl:gap-x-3`}>
        <div className="flex min-w-0 flex-col gap-3">
          <JurisdictionBanner blueprint={blueprint} companyId={company.id} variant="overview" />

          <section aria-labelledby="how-heading" className="rounded-[1.25rem] border border-hero-border bg-white p-5 shadow-hero-card">
            <h2 className="text-[1.75rem] font-extrabold tracking-[-0.02em] text-hero-navy" id="how-heading">
              How it works
            </h2>
            <p className="mt-1 max-w-[46rem] text-base leading-relaxed text-hero-muted">
              Every case follows the same careful pattern: HeroOS guides and keeps the record; you make every decision.
            </p>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-[#d6e4fa] bg-[#f3f7fe] p-5">
                <div className="flex items-start gap-3">
                  <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-[#dce8fc] text-hero-blue">
                    <DocumentIcon className="size-6" />
                  </span>
                  <div>
                    <h3 className="text-[1.1875rem] font-extrabold text-hero-navy">What HeroOS guides</h3>
                    <p className="text-[0.9375rem] text-hero-muted">The same structured steps for every case.</p>
                  </div>
                </div>
                <Points points={GUIDED} tone="blue" />
              </div>
              <div className="rounded-2xl border border-[#f1e2a6] bg-[#fffaea] p-5">
                <div className="flex items-start gap-3">
                  <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-hero-yellow-tint text-hero-navy">
                    <ShieldIcon className="size-6" />
                  </span>
                  <div>
                    <h3 className="text-[1.1875rem] font-extrabold text-hero-navy">What stays with you</h3>
                    <p className="text-[0.9375rem] text-hero-muted">HeroOS never decides for you.</p>
                  </div>
                </div>
                <Points points={YOURS} tone="yellow" />
              </div>
            </div>
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <section aria-labelledby="availability-heading" className="rounded-[1.25rem] border border-hero-border bg-white p-5 shadow-hero-card">
            <h2 className="text-[1.1875rem] font-extrabold text-hero-navy" id="availability-heading">
              Workflow availability
            </h2>
            <ul className="mt-2 divide-y divide-hero-border">
              <AvailabilityRow
                icon={roundIcon("positive", <CheckIcon className="size-4" />)}
                status="Available"
                title="Create and record cases"
                tone="positive"
              />
              <AvailabilityRow
                detail={
                  confirmed
                    ? "Where approved workflow rules are installed."
                    : "Needs a confirmed jurisdiction and approved workflow rules."
                }
                icon={roundIcon(confirmed ? "positive" : "caution", <ClockIcon className="size-4" />)}
                status={confirmed ? "Where installed" : "Restricted"}
                title="Guided next steps"
                tone={confirmed ? "neutral" : "caution"}
              />
              <AvailabilityRow
                detail="Previews only, never issued or sent."
                icon={roundIcon("muted", <LockIcon className="size-4" />)}
                status="Not available"
                title="Issue final documents"
                tone="muted"
              />
            </ul>
          </section>

          <section aria-labelledby="useful-heading" className="rounded-[1.25rem] border border-hero-border bg-white p-5 shadow-hero-card">
            <div className="flex items-center gap-3">
              <BookIcon className="size-7 text-hero-navy" />
              <h2 className="text-[1.1875rem] font-extrabold text-hero-navy" id="useful-heading">
                Useful links
              </h2>
            </div>
            <ul className="mt-3 overflow-hidden rounded-xl border border-hero-border">
              {[
                { label: "All disciplinary cases", href: listHref },
                { label: "Company Blueprint and jurisdiction", href: `${base}/settings` },
                { label: "All HR services", href: `${base}/hr-services` },
              ].map((link) => (
                <li className="border-t border-hero-border first:border-t-0" key={link.href}>
                  <a
                    className="flex min-h-12 items-center justify-between gap-3 px-4 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint/50"
                    href={link.href}
                  >
                    {link.label}
                    <ChevronRightIcon className="size-4 shrink-0 text-hero-blue-ink" />
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <a className={`${buttonPrimary} min-h-14 w-full rounded-xl px-5 text-base`} href={`${listHref}/new`}>
            <PlusIcon className="size-5" />
            Create a new disciplinary case
            <ArrowRightIcon className="size-4" />
          </a>
        </div>

        <section
          aria-labelledby="recent-heading"
          className="rounded-[1.25rem] border border-hero-border bg-white p-4 shadow-hero-card sm:p-5 xl:col-span-2"
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="inline-flex size-11 items-center justify-center rounded-full bg-hero-blue-tint text-hero-blue">
                <DocumentIcon className="size-6" />
              </span>
              <div>
                <h2 className="text-[1.1875rem] font-extrabold text-hero-navy" id="recent-heading">
                  Recent cases
                </h2>
                <p className="text-[0.9375rem] text-hero-muted">Your company&apos;s most recently active cases.</p>
              </div>
            </div>
            <a
              className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-[0.9375rem] font-bold text-hero-blue-ink underline underline-offset-4"
              href={listHref}
            >
              View all cases
              <ArrowRightIcon className="size-4" />
            </a>
          </div>
          <CasesTable
            cases={cases}
            companyId={company.id}
            controls={false}
            empty={
              <p className="rounded-2xl border border-dashed border-hero-control/60 px-5 py-6 text-[0.9375rem] text-hero-muted">
                No cases yet. Create one when a conduct concern comes up.
              </p>
            }
            limit={3}
          />
        </section>
      </div>
    </>
  );
}
