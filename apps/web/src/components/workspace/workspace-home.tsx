import type { ReactNode } from "react";

import {
  ArrowRightIcon,
  BuildingIcon,
  CaseIcon,
  CheckIcon,
  DocumentIcon,
  InfoIcon,
  ScaleIcon,
} from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import { licensingLabel, readinessCopy, roleLabel } from "@/lib/onboarding/copy";
import type { Blueprint, WorkspaceDetails } from "@/lib/server/heroos-api";

import { HannahScene, pageGutter } from "./page-banner";
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

/** Each step's status as a small symbol beside its words. */
export function StepMark({ tone }: { tone: Step["tone"] }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex size-6 shrink-0 items-center justify-center rounded-full ${
        tone === "positive"
          ? "bg-hero-success text-white"
          : tone === "caution" || tone === "neutral"
            ? "bg-hero-yellow text-hero-navy"
            : "bg-hero-bg text-hero-muted"
      }`}
    >
      {tone === "positive" ? <CheckIcon className="size-3.5" /> : <span className="size-1.5 rounded-full bg-current" />}
    </span>
  );
}

const panel = "rounded-[1.25rem] border border-hero-border bg-white shadow-hero-card";

function Fact({ term, children }: { term: string; children: string | null }) {
  return (
    <div className="py-1.5">
      <dt className="text-sm text-hero-muted">{term}</dt>
      <dd className="mt-0.5 break-words text-[0.9375rem] font-semibold text-hero-navy">
        {children ?? <span className="font-normal text-hero-muted">Not provided</span>}
      </dd>
    </div>
  );
}

function ActionCard({
  icon,
  title,
  children,
  action,
  tint,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action: ReactNode;
  tint: "blue" | "yellow";
}) {
  return (
    <li
      className={`flex flex-col rounded-[1.25rem] border p-5 ${
        tint === "blue" ? "border-[#dbe7fb] bg-[#f3f7fe]" : "border-[#f3e6b3] bg-[#fffaea]"
      }`}
    >
      <span
        aria-hidden="true"
        className={`inline-flex size-[4.25rem] items-center justify-center rounded-full ${
          tint === "blue" ? "bg-[#dce8fc] text-hero-blue" : "bg-hero-yellow-tint text-hero-navy"
        }`}
      >
        {icon}
      </span>
      <h3 className="mt-5 text-[1.1875rem] font-extrabold leading-snug tracking-[-0.01em] text-hero-navy">{title}</h3>
      <p className="mt-1.5 flex-1 text-[0.9375rem] leading-relaxed text-hero-muted">{children}</p>
      <div className="mt-5">{action}</div>
    </li>
  );
}

/** WORKSPACE_READY: the authorized Company's dashboard (JJ design review, screen 06). */
export function WorkspaceHome({ details }: { details: WorkspaceDetails }) {
  const { company, membership, blueprint, cases } = details;
  const role = roleLabel(membership?.role ?? null);
  const canEdit = membership?.canUpdateBlueprint === true;
  // Disciplinary Cases are administrator-only (M2-01); the API enforces it.
  const admin = membership?.role === "company_admin";
  const base = `/workspaces/${encodeURIComponent(company.id)}`;
  const settingsHref = `${base}/settings`;
  const readiness = blueprint ? readinessCopy(blueprint.jurisdiction) : null;
  const confirmed = readiness?.tone === "positive";
  const steps = setupSteps(blueprint);

  return (
    <div className={`${pageGutter} flex flex-col gap-6 pb-10 lg:gap-7`}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] xl:gap-x-[1.125rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <header className="pt-7 sm:pt-10 xl:min-h-[10rem] xl:pt-[3.25rem]">
            <h1 className="text-[2rem] font-extrabold leading-[1.1] tracking-[-0.03em] text-hero-navy sm:text-[2.5rem] xl:text-[2.75rem]">
              Welcome to{" "}
              <span className="bg-[linear-gradient(transparent_62%,var(--hero-yellow)_62%,var(--hero-yellow)_92%,transparent_92%)] px-0.5">
                HeroOS
              </span>
            </h1>
            <p className="mt-3 flex max-w-[34rem] flex-wrap items-center gap-x-2.5 gap-y-1 text-base text-hero-muted sm:text-[1.0625rem]">
              <span>Here&apos;s an overview of your company&apos;s workspace.</span>
              {role ? <StatusBadge tone={canEdit ? "positive" : "neutral"}>{role}</StatusBadge> : null}
            </p>
          </header>

          <section aria-labelledby="company-info-heading" className={`${panel} px-5 py-5 sm:px-6`}>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hero-border pb-3.5">
              <div className="flex items-center gap-3">
                <span className="inline-flex size-11 items-center justify-center rounded-full bg-hero-bg text-hero-navy">
                  <BuildingIcon className="size-6" />
                </span>
                <h2 className="text-[1.1875rem] font-extrabold tracking-[-0.01em] text-hero-navy" id="company-info-heading">
                  Your company at a glance
                </h2>
              </div>
              {blueprint !== null ? (
                <a className={`${buttonSecondary} min-h-11 rounded-xl px-4 text-[0.9375rem]`} href={settingsHref}>
                  {canEdit ? "Edit company details" : "View company details"}
                  <ArrowRightIcon className="size-4" />
                </a>
              ) : null}
            </div>
            {blueprint !== null ? (
              <>
                <div className="grid pt-2 sm:grid-cols-2 sm:divide-x sm:divide-hero-border">
                  <dl className="sm:pr-6">
                    <Fact term="Company name">{company.name}</Fact>
                    <Fact term="Legal business name">{blueprint.legalName}</Fact>
                    <Fact term="Industry">{blueprint.industry}</Fact>
                  </dl>
                  <dl className="sm:pl-8">
                    <Fact term="Number of employees">
                      {blueprint.employeeCount === null ? null : blueprint.employeeCount.toLocaleString("en-US")}
                    </Fact>
                    <Fact term="Licensed in">
                      {blueprint.licensing.location === null ? null : licensingLabel(blueprint.licensing.location)}
                    </Fact>
                    {blueprint.licensing.location === "other" ? (
                      <Fact term="Licensing authority">{blueprint.licensing.authority}</Fact>
                    ) : null}
                  </dl>
                </div>
                {!canEdit ? (
                  <p className="mt-2 text-sm text-hero-muted">Only company administrators can change these details.</p>
                ) : null}
              </>
            ) : (
              <Notice className="mt-4" title="Company profile isn't available yet">
                This HeroOS service doesn&apos;t provide company profiles yet. Your workspace is still available.
              </Notice>
            )}
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-[0.875rem]">
          <HannahScene
            bubble="Here's your HeroOS workspace. Let's get started!"
            bubbleOut
            className="relative -mr-[1.5625rem] hidden h-[14.875rem] xl:block"
          />
          {readiness ? (
            <section
              aria-labelledby="jurisdiction-heading"
              className={`flex flex-1 flex-col rounded-[1.25rem] border px-5 py-5 shadow-hero-card ${
                confirmed ? "border-[#b8dcc6] bg-hero-success-tint" : "border-[#f1e2a6] bg-[#fffaea]"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span
                    className={`inline-flex size-11 items-center justify-center rounded-full ${
                      confirmed ? "bg-white text-hero-success" : "bg-hero-yellow text-hero-navy"
                    }`}
                  >
                    <ScaleIcon className="size-6" />
                  </span>
                  <h2 className="text-[1.1875rem] font-extrabold tracking-[-0.01em] text-hero-navy" id="jurisdiction-heading">
                    Jurisdiction status
                  </h2>
                </div>
                <StatusBadge tone={readiness.tone === "positive" ? "positive" : readiness.tone === "caution" ? "caution" : "neutral"}>
                  {readiness.status}
                </StatusBadge>
              </div>
              <h3 className="mt-4 text-base font-bold text-hero-navy">{readiness.title}</h3>
              <p className="mt-1 flex-1 text-[0.9375rem] leading-relaxed text-hero-navy/80">{readiness.body}</p>
              <a
                className={`${buttonSecondary} mt-4 min-h-11 self-start rounded-xl px-4 text-[0.9375rem]`}
                href={settingsHref}
              >
                View details
                <ArrowRightIcon className="size-4" />
              </a>
            </section>
          ) : null}
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,2.85fr)_minmax(0,1.3fr)] xl:gap-x-5">
        <section aria-labelledby="actions-heading" className="min-w-0">
          <h2 className="text-[1.5rem] font-extrabold tracking-[-0.02em] text-hero-navy" id="actions-heading">
            What you can do now
          </h2>
          <ul className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <ActionCard
              action={
                <a className={`${buttonPrimary} min-h-12 w-full rounded-xl px-4 text-[0.9375rem]`} href={`${base}/hr-services`}>
                  Go to HR Services
                  <ArrowRightIcon className="size-4" />
                </a>
              }
              icon={<CaseIcon className="size-8" />}
              tint="blue"
              title="Explore HR Services"
            >
              See the HR workflows for your company and what each one offers today.
            </ActionCard>
            <ActionCard
              action={
                blueprint !== null ? (
                  <a className={`${buttonSecondary} min-h-12 w-full rounded-xl px-4 text-[0.9375rem]`} href={settingsHref}>
                    Company Blueprint
                    <ArrowRightIcon className="size-4" />
                  </a>
                ) : (
                  <p className="text-sm font-semibold text-hero-muted">Not available from this HeroOS service yet.</p>
                )
              }
              icon={<BuildingIcon className="size-8" />}
              tint="yellow"
              title="Manage your company"
            >
              {canEdit
                ? "Review or update your company's details and licensing information."
                : "See your company's saved details and licensing information."}
            </ActionCard>
            <ActionCard
              action={
                admin ? (
                  <a className={`${buttonPrimary} min-h-12 w-full rounded-xl px-4 text-[0.9375rem]`} href={`${base}/cases`}>
                    Go to Cases
                    <ArrowRightIcon className="size-4" />
                  </a>
                ) : (
                  <StatusBadge tone="muted">Administrators only</StatusBadge>
                )
              }
              icon={<DocumentIcon className="size-8" />}
              tint="blue"
              title="Disciplinary cases"
            >
              {admin
                ? "Start a confidential case, or continue one where you left off."
                : "Disciplinary cases are confidential: only your company's administrators can open them."}
            </ActionCard>
          </ul>
        </section>
        <WorkflowAreas
          admin={admin}
          blueprint={blueprint}
          className="self-start rounded-[1.25rem] border border-dashed border-[#d5dcea] bg-white px-5 py-4 xl:mt-[0.75rem]"
          companyId={company.id}
        />
      </div>

      <section
        aria-labelledby="next-steps-heading"
        className="flex flex-col gap-4 rounded-[1.25rem] border border-[#d6e4fa] bg-hero-blue-tint/70 px-5 py-5 sm:flex-row sm:px-6"
      >
        <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-hero-blue text-white">
          <InfoIcon className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[1.1875rem] font-extrabold tracking-[-0.01em] text-hero-navy" id="next-steps-heading">
            Next steps
          </h2>
          <p className="mt-1 max-w-[62rem] text-[0.9375rem] leading-relaxed text-hero-navy/85">
            {readiness === null
              ? "Your workspace is ready. Company profiles aren't provided by this HeroOS service yet."
              : confirmed
                ? `Your jurisdiction is confirmed. ${
                    admin
                      ? "Open Disciplinary cases to start a case or continue one."
                      : "Your company's administrators can open Disciplinary cases."
                  }`
                : `${readiness.body} In the meantime, you can explore your workspace${
                    admin ? ", start Disciplinary cases" : ""
                  } and keep your company details up to date.`}
          </p>
          <ul aria-label="Company setup" className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
            {steps.map((step) => (
              <li className="flex items-center gap-2 text-sm font-semibold text-hero-navy" key={step.label}>
                <StepMark tone={step.tone} />
                {step.label}:
                <span className="font-normal text-hero-navy/80">{step.status}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {cases.length > 0 ? (
        <section aria-labelledby="cases-heading" className={`${panel} px-5 py-5 sm:px-6`}>
          <h2 className="text-[1.1875rem] font-extrabold tracking-[-0.01em] text-hero-navy" id="cases-heading">
            Case records
          </h2>
          <p className="mt-1 text-[0.9375rem] text-hero-muted">
            Records saved for this company. Disciplinary cases open in the guided workspace.
          </p>
          <ul aria-label="Cases" className="mt-4 grid gap-2 md:grid-cols-2">
            {cases.map((item) =>
              item.caseType === "disciplinary" && admin ? (
                <li key={item.id}>
                  <a
                    className="block rounded-xl border border-hero-border px-4 py-3 transition-colors duration-150 hover:bg-hero-blue-tint/60"
                    href={`${base}/cases/${encodeURIComponent(item.id)}`}
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
