import { ArrowRightIcon, CaseIcon, CheckIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonSecondary, card, lede, sectionTitle } from "@/components/ui/styles";
import { readinessCopy, roleLabel } from "@/lib/onboarding/copy";
import type { Blueprint, WorkspaceDetails } from "@/lib/server/heroos-api";

import { CompanyFacts } from "./company-facts";
import { JurisdictionStatus } from "./jurisdiction-status";
import { WorkflowAreas } from "./workflow-areas";

type Step = { label: string; status: string; tone: "positive" | "neutral" | "caution" | "muted" };

/** Setup progress in words; each status comes from saved data or the API's readiness. */
export function setupSteps(blueprint: Blueprint | null): Step[] {
  const steps: Step[] = [{ label: "Workspace created", status: "Done", tone: "positive" }];
  if (blueprint === null) return steps;
  const detailsAdded = [blueprint.legalName, blueprint.industry, blueprint.employeeCount].some((value) => value !== null);
  steps.push({
    label: "Company details",
    status: detailsAdded ? "Added" : "Not added yet",
    tone: detailsAdded ? "positive" : "muted",
  });
  const { location, authority } = blueprint.licensing;
  steps.push(
    location === null
      ? { label: "Licensing details", status: "Not provided", tone: "muted" }
      : location === "not_sure"
        ? { label: "Licensing details", status: "Not sure yet", tone: "neutral" }
        : location === "other" && authority === null
          ? { label: "Licensing details", status: "Authority missing", tone: "neutral" }
          : { label: "Licensing details", status: "Provided", tone: "positive" },
  );
  const readiness = readinessCopy(blueprint.jurisdiction);
  steps.push({
    label: "Jurisdiction",
    status: readiness.status,
    tone: readiness.tone === "positive" ? "positive" : readiness.tone === "caution" ? "caution" : "neutral",
  });
  return steps;
}

/** WORKSPACE_READY: the authorized Company's home. */
export function WorkspaceHome({ details }: { details: WorkspaceDetails }) {
  const { company, membership, blueprint, cases } = details;
  const role = roleLabel(membership?.role ?? null);
  const canEdit = membership?.canUpdateBlueprint === true;
  const settingsHref = `/workspaces/${encodeURIComponent(company.id)}/settings`;

  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-4 py-8 sm:gap-8 sm:px-8 sm:py-12">
      <header className="flex flex-col gap-3">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">Company workspace</p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 break-words text-[1.875rem] font-extrabold leading-tight tracking-[-0.025em] text-hero-navy sm:text-[2.5rem]">
            {company.name}
          </h1>
          {role ? <StatusBadge tone={canEdit ? "positive" : "neutral"}>{role}</StatusBadge> : null}
        </div>
        <p className={`max-w-[44rem] ${lede}`}>
          Welcome to HeroOS. This is your company&apos;s workspace: your company details live here now, and your guided
          HR workflows will appear here as they become available.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)] lg:gap-8">
        <section aria-labelledby="company-info-heading" className={`${card} p-5 sm:p-8`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className={sectionTitle} id="company-info-heading">
              Company information
            </h2>
            {blueprint !== null ? (
              <a className={`${buttonSecondary} min-h-11 px-5 text-sm`} href={settingsHref}>
                {canEdit ? "Edit company details" : "View company details"}
                <ArrowRightIcon className="size-4" />
              </a>
            ) : null}
          </div>
          {blueprint !== null ? (
            <>
              <div className="mt-3">
                <CompanyFacts blueprint={blueprint} />
              </div>
              <div className="mt-5">
                <JurisdictionStatus jurisdiction={blueprint.jurisdiction} />
              </div>
              {!canEdit ? (
                <p className="mt-4 text-sm text-hero-muted">Only company administrators can change these details.</p>
              ) : null}
            </>
          ) : (
            <Notice className="mt-4" title="Company profile isn't available yet">
              This HeroOS service doesn&apos;t provide company profiles yet. Your workspace is still available.
            </Notice>
          )}
        </section>

        <section aria-labelledby="setup-heading" className={`${card} p-5 sm:p-8`}>
          <h2 className={sectionTitle} id="setup-heading">
            Company setup
          </h2>
          <ul className="mt-4 flex flex-col gap-1">
            {setupSteps(blueprint).map((step) => (
              <li className="flex min-h-12 items-center justify-between gap-3 border-b border-hero-border py-2 last:border-b-0" key={step.label}>
                <span className="flex items-center gap-2.5 text-[0.9375rem] font-semibold text-hero-navy">
                  <span
                    aria-hidden="true"
                    className={`inline-flex size-6 shrink-0 items-center justify-center rounded-full ${
                      step.tone === "positive" ? "bg-hero-success-tint text-hero-success" : "bg-hero-bg text-hero-muted"
                    }`}
                  >
                    {step.tone === "positive" ? <CheckIcon className="size-3.5" /> : <span className="size-1.5 rounded-full bg-current" />}
                  </span>
                  {step.label}
                </span>
                <StatusBadge tone={step.tone}>{step.status}</StatusBadge>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <WorkflowAreas companyId={company.id} />

      {cases.length > 0 ? (
        <section aria-labelledby="cases-heading" className={`${card} p-5 sm:p-8`}>
          <div className="flex items-start gap-3">
            <CaseIcon className="mt-0.5 size-6 shrink-0 text-hero-blue" />
            <div>
              <h2 className={sectionTitle} id="cases-heading">
                Case records
              </h2>
              <p className="mt-1 text-[0.9375rem] text-hero-muted">Records saved for this company. Disciplinary cases open in the guided workspace.</p>
            </div>
          </div>
          <ul aria-label="Cases" className="mt-5 flex flex-col gap-2">
            {cases.map((item) =>
              item.caseType === "disciplinary" ? (
                <li key={item.id}>
                  <a
                    className="block rounded-xl border border-hero-border px-4 py-3 transition-colors duration-150 hover:bg-hero-blue-tint/60 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-hero-blue"
                    href={`/workspaces/${encodeURIComponent(company.id)}/cases/${encodeURIComponent(item.id)}`}
                  >
                    <span className="block break-words font-semibold text-hero-navy">{item.title}</span>
                    <span className="block text-sm capitalize text-hero-muted">{item.caseType}</span>
                  </a>
                </li>
              ) : (
                <li className="rounded-xl border border-hero-border px-4 py-3" key={item.id}>
                  <p className="break-words font-semibold text-hero-navy">{item.title}</p>
                  <p className="text-sm capitalize text-hero-muted">{item.caseType}</p>
                </li>
              ),
            )}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
