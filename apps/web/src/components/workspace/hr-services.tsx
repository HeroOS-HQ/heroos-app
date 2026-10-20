import { ArrowRightIcon, BookIcon, CheckIcon, LightbulbIcon, LockIcon, ScaleIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import type { WorkspaceDetails } from "@/lib/server/heroos-api";

import { PageBanner, pageGutter } from "./page-banner";
import { WORKFLOWS, jurisdictionConfirmed, workflowAvailability } from "./workflow-areas";
import { setupSteps, StepMark } from "./workspace-home";

/** What Disciplinary does today: product behaviour only, never a legal step. */
const DISCIPLINARY_FEATURES = [
  "Guided intake questions, with fixed checks that can pause a case for specialist advice",
  "Your decision records, corrections and a complete case history",
  "Document previews where approved templates are installed (never issued)",
];

/** HR Services (JJ design review, screen 07): the three V1 workflows and what each offers this account today. */
export function HrServices({ details }: { details: WorkspaceDetails }) {
  const { company, membership, blueprint } = details;
  const admin = membership?.role === "company_admin";
  const confirmed = jurisdictionConfirmed(blueprint);
  const settingsHref = `/workspaces/${encodeURIComponent(company.id)}/settings`;

  return (
    <>
      <PageBanner bubble="Here are the HR workflows for your business!" title="HR Services">
        <p className="text-[1.125rem] text-hero-navy/85 sm:text-[1.25rem]">Explore the HR workflows available for your business.</p>
        <p className="mt-1.5 max-w-[34rem]">
          Some steps need your company&apos;s employment jurisdiction to be confirmed before they can be used.
        </p>
      </PageBanner>

      <div className={`${pageGutter} grid gap-4 pb-10 xl:grid-cols-[minmax(0,1fr)_26.5rem] xl:gap-5`}>
        <ul aria-label="HR workflows" className="flex min-w-0 flex-col gap-3.5">
          {WORKFLOWS.map((workflow) => {
            const availability = workflowAvailability(workflow.key, { companyId: company.id, admin, blueprint });
            const disciplinary = workflow.key === "disciplinary";
            return (
              <li
                className={`flex flex-col gap-5 rounded-[1.25rem] border p-5 sm:flex-row sm:p-6 ${
                  disciplinary ? "border-[#f1e2a6] bg-[#fffaea]" : "border-[#dde6f4] bg-[#f4f7fc]"
                }`}
                key={workflow.key}
              >
                <span
                  aria-hidden="true"
                  className={`inline-flex size-[4.75rem] shrink-0 items-center justify-center rounded-full ${
                    disciplinary ? "bg-hero-yellow-tint text-hero-navy" : "bg-[#e3ebf8] text-hero-blue-ink"
                  }`}
                >
                  {workflow.icon("size-9")}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                    <h2 className="text-[1.5rem] font-extrabold tracking-[-0.02em] text-hero-navy">{workflow.title}</h2>
                    <span className="inline-flex items-center gap-1.5">
                      {availability.href ? null : <LockIcon className="size-4 text-hero-muted" />}
                      <StatusBadge tone={availability.tone}>{availability.label}</StatusBadge>
                    </span>
                  </div>
                  <p className="mt-1.5 max-w-[34rem] text-base leading-relaxed text-hero-muted">{workflow.description}</p>
                  <div className="mt-4 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                    {disciplinary ? (
                      <ul className="flex flex-col gap-2">
                        {DISCIPLINARY_FEATURES.map((feature) => (
                          <li className="flex items-start gap-2.5 text-[0.9375rem] text-hero-navy/85" key={feature}>
                            <span
                              aria-hidden="true"
                              className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-hero-yellow text-hero-navy"
                            >
                              <CheckIcon className="size-3" />
                            </span>
                            {feature}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-[0.9375rem] text-hero-muted">{availability.detail}</p>
                    )}
                    {availability.href ? (
                      // The one workflow this account can open: the page's primary action.
                      <a
                        className={`${buttonPrimary} min-h-12 shrink-0 rounded-xl px-6 text-[0.9375rem]`}
                        href={availability.href}
                      >
                        View details
                        <ArrowRightIcon className="size-4" />
                      </a>
                    ) : disciplinary ? (
                      <p className="max-w-[18rem] text-sm text-hero-muted">{availability.detail}</p>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="flex min-w-0 flex-col gap-3.5">
          <section aria-labelledby="setup-heading" className="rounded-[1.25rem] border border-[#f1e2a6] bg-[#fffaea] p-5">
            <div className="flex items-center gap-3">
              <ScaleIcon className="size-6 text-hero-navy" />
              <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id="setup-heading">
                Your setup status
              </h2>
            </div>
            <ul className="mt-3 flex flex-col">
              {setupSteps(blueprint).map((step) => (
                <li className="flex items-center gap-3 border-t border-[#f1e2a6]/70 py-2.5 first:border-t-0" key={step.label}>
                  <StepMark tone={step.tone} />
                  <span className="min-w-0 flex-1 text-[0.9375rem] font-bold text-hero-navy">{step.label}</span>
                  <StatusBadge tone={step.tone}>{step.status}</StatusBadge>
                </li>
              ))}
            </ul>
          </section>

          {blueprint !== null && !confirmed ? (
            <section aria-labelledby="first-heading" className="rounded-[1.25rem] border border-[#d6e4fa] bg-hero-blue-tint/70 p-5">
              <div className="flex items-start gap-3">
                <LightbulbIcon className="mt-0.5 size-6 shrink-0 text-hero-blue" />
                <div>
                  <h2 className="text-[1.1875rem] font-extrabold text-hero-navy" id="first-heading">
                    Need to complete first?
                  </h2>
                  <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-hero-navy/85">
                    Your employment jurisdiction still needs to be confirmed before jurisdiction-specific guidance is
                    available. You can still create and record Disciplinary cases.
                  </p>
                  {/* Secondary: HeroOS confirms the jurisdiction; this only shows where it stands. */}
                  <a className={`${buttonSecondary} mt-4 min-h-12 rounded-xl px-5 text-[0.9375rem]`} href={settingsHref}>
                    View jurisdiction details
                    <ArrowRightIcon className="size-4" />
                  </a>
                </div>
              </div>
            </section>
          ) : null}

          <section aria-labelledby="about-heading" className="rounded-[1.25rem] border border-hero-border bg-white p-5 shadow-hero-card">
            <div className="flex items-start gap-3">
              <BookIcon className="mt-0.5 size-6 shrink-0 text-hero-navy" />
              <div>
                <h2 className="text-[1.1875rem] font-extrabold text-hero-navy" id="about-heading">
                  About HR services
                </h2>
                <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-hero-muted">
                  Workflows are added step by step. HeroOS guides and keeps the record; you make and record every
                  decision, and nothing is issued on your behalf.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
