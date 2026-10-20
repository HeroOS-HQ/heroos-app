import type { ReactNode } from "react";

import { IconRow } from "@/components/onboarding/onboarding-field";
import {
  ActionBar,
  GuidanceCard,
  onboardingLink,
  OnboardingStage,
  onboardingPrimary,
  StageCard,
} from "@/components/onboarding/onboarding-frame";
import {
  ArrowRightIcon,
  BuildingIcon,
  ChartIcon,
  CheckIcon,
  ClockIcon,
  DocumentIcon,
} from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { licensingLabel, readinessCopy } from "@/lib/onboarding/copy";
import type { Blueprint, WorkspaceDetails } from "@/lib/server/heroos-api";

/**
 * Complete, the fifth stage of setup (JJ design review, screen 05), after a
 * confirmed registration only (REGISTRATION_CREATED or REGISTRATION_EXISTING).
 * Everything shown is read back from the API: the Company name, the role, the
 * Blueprint and the jurisdiction readiness. Workspace creation is never
 * presented as a legal or jurisdiction confirmation, and an existing workspace
 * is never presented as newly created.
 */
export function WorkspaceReady({ details, outcome }: { details: WorkspaceDetails; outcome: "created" | "existing" }) {
  const { company, membership, blueprint } = details;
  const base = `/workspaces/${encodeURIComponent(company.id)}`;
  const admin = membership?.role === "company_admin";
  const canEdit = membership?.canUpdateBlueprint === true;
  const created = outcome === "created";
  const readiness = blueprint ? readinessCopy(blueprint.jurisdiction) : null;
  const confirmed = readiness?.tone === "positive";

  return (
    <OnboardingStage
      actions={
        <ActionBar
          end={
            <a className={`${onboardingPrimary} sm:min-w-[14.5rem]`} href={base}>
              Open my workspace
              <ArrowRightIcon className="size-5 stroke-[2.25]" />
            </a>
          }
        />
      }
      bubble={created ? "All set! You're ready to explore HeroOS!" : "Welcome back! Your workspace is right here."}
      guidance={
        <GuidanceCard
          items={[
            created
              ? "Your company details are saved in Company Blueprint."
              : "Nothing new was created: the details on record are unchanged.",
            confirmed
              ? "Your jurisdiction is confirmed, as your setup status shows."
              : "Your jurisdiction is confirmed separately. Jurisdiction-specific guidance waits for that.",
            canEdit
              ? "Explore your workspace now, and update the optional details whenever you need to."
              : "Open your workspace to see what's available to you now.",
          ]}
          numbered
          title="What happens next?"
        />
      }
      stage="complete"
    >
      <StageCard
        accent={created ? "is ready" : "a workspace"}
        intro={
          created ? (
            <p>
              <strong className="font-bold text-hero-navy">{company.name}</strong> is set up on HeroOS
              {admin ? ", and you're its administrator." : "."}
              {confirmed ? null : " Some HR features need a confirmed jurisdiction before they're available."}
            </p>
          ) : (
            <p>
              We found the company workspace you set up earlier:{" "}
              <strong className="font-bold text-hero-navy">{company.name}</strong>.
            </p>
          )
        }
        lead={created ? "Your workspace" : "You already have"}
        stage="complete"
      >
        {created ? null : (
          // Also true after a retry of an uncertain first attempt that did create it.
          <Notice className="mt-5" title="Your existing workspace wasn't changed">
            Your account can set up one company workspace by itself, so nothing new was created and HeroOS kept the
            details already on record.
            {admin ? " Check them from your workspace and update them if needed." : null}
          </Notice>
        )}

        <div className="mt-5">
          <IconRow align="top" icon={<BuildingIcon className="size-6" />}>
            <section aria-labelledby="ready-status" className="rounded-xl border border-hero-border bg-[#f8f9fc] px-4 pb-0.5 pt-2.5">
              <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id="ready-status">
                Setup status
              </h2>
              <ul className="mt-1 divide-y divide-hero-border">
                <StatusRow
                  action={canEdit ? { href: `${base}/settings`, label: "Edit", context: "company information" } : undefined}
                  detail={companySummary(blueprint)}
                  status={created ? "Saved" : "On record"}
                  title="Company information"
                />
                {blueprint ? (
                  <StatusRow
                    action={canEdit ? { href: `${base}/settings`, label: "Edit", context: "licence details" } : undefined}
                    detail={licensingSummary(blueprint)}
                    pending={blueprint.licensing.location === null}
                    status={blueprint.licensing.location === null ? "Not provided" : created ? "Saved" : "On record"}
                    title="Licence details"
                  />
                ) : null}
                <StatusRow
                  action={{ href: `${base}/settings`, label: "Open", context: "Company Blueprint" }}
                  status={canEdit ? "Available to review and update" : "Available to view"}
                  title="Company Blueprint"
                />
                {readiness ? (
                  <StatusRow
                    badge={<StatusBadge tone={readiness.tone === "positive" ? "positive" : "caution"}>{readiness.status}</StatusBadge>}
                    detail={readiness.body}
                    heading
                    pending={!confirmed}
                    title={readiness.title}
                  />
                ) : null}
              </ul>
            </section>
          </IconRow>
        </div>

        <section aria-labelledby="ready-next" className="mt-4">
          <h2 className="text-xl font-extrabold tracking-[-0.01em] text-hero-navy" id="ready-next">
            What you can do now
          </h2>
          <ul className="mt-2.5 grid gap-3 md:grid-cols-3">
            <NextAction
              body="Go to your dashboard and see what's available."
              cta="Go to workspace"
              href={base}
              icon={<ChartIcon className="size-6" />}
              title="Explore your workspace"
            />
            <NextAction
              body={canEdit ? "Check or update your company details." : "See your company details."}
              cta="Open Blueprint"
              href={`${base}/settings`}
              icon={<BuildingIcon className="size-6" />}
              title="Review Company Blueprint"
            />
            <NextAction
              body="See the HR workflows available to your company."
              cta="View HR services"
              href={`${base}/hr-services`}
              icon={<DocumentIcon className="size-6" />}
              title="View HR services"
            />
          </ul>
        </section>
      </StageCard>
    </OnboardingStage>
  );
}

/** The optional company details on record, in one line (the name is in the introduction). */
function companySummary(blueprint: Blueprint | null): string {
  if (blueprint === null) return "Company name";
  const parts = [
    blueprint.legalName,
    blueprint.industry,
    blueprint.employeeCount === null
      ? null
      : `${blueprint.employeeCount.toLocaleString("en-US")} employee${blueprint.employeeCount === 1 ? "" : "s"}`,
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : "Company name only; no optional details given.";
}

function licensingSummary(blueprint: Blueprint): string {
  const { location, authority } = blueprint.licensing;
  if (location === null) return "No licensing details yet.";
  if (location !== "other") return licensingLabel(location);
  return `${licensingLabel(location)} · ${authority ?? "Authority not given"}`;
}

function StatusRow({
  title,
  status,
  detail,
  badge,
  action,
  pending = false,
  heading = false,
}: {
  title: string;
  status?: string;
  detail?: string;
  badge?: ReactNode;
  action?: { href: string; label: string; context: string };
  pending?: boolean;
  /** The jurisdiction row's title is a heading (it states the readiness). */
  heading?: boolean;
}) {
  const Title = heading ? "h3" : "p";
  return (
    <li className="flex items-start gap-3 py-2">
      <span
        aria-hidden="true"
        className={`mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full ${
          pending ? "bg-hero-yellow text-hero-navy" : "bg-hero-success text-white"
        }`}
      >
        {pending ? <ClockIcon className="size-[1.125rem]" /> : <CheckIcon className="size-4 stroke-[3]" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Title className="text-base font-bold text-hero-navy">{title}</Title>
          {badge}
        </div>
        {heading ? (
          detail ? <p className="mt-0.5 break-words text-sm leading-relaxed text-hero-navy/80">{detail}</p> : null
        ) : (
          <p className="break-words text-sm leading-relaxed text-hero-muted">
            {status}
            {detail ? <span className="text-hero-navy/80"> · {detail}</span> : null}
          </p>
        )}
      </div>
      {action ? (
        <a className={`${onboardingLink} -my-2 shrink-0`} href={action.href}>
          {`${action.label} `}
          <span className="sr-only">{action.context}</span>
        </a>
      ) : null}
    </li>
  );
}

function NextAction({ title, body, cta, href, icon }: { title: string; body: string; cta: string; href: string; icon: ReactNode }) {
  return (
    <li className="flex flex-col rounded-xl border border-hero-border bg-white p-3.5">
      <div className="flex flex-1 items-start gap-2.5">
        <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-hero-blue-tint text-hero-navy">
          {icon}
        </span>
        <div className="min-w-0">
          <p className="text-[0.875rem] font-bold leading-snug text-hero-navy">{title}</p>
          <p className="mt-0.5 text-[0.8125rem] leading-snug text-hero-muted">{body}</p>
        </div>
      </div>
      <a
        className="mt-3 inline-flex min-h-11 items-center justify-center gap-2 rounded-[0.625rem] bg-hero-yellow px-3 text-[0.9375rem] font-bold text-hero-navy transition-colors duration-150 hover:bg-[#f6cb00] focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue"
        href={href}
      >
        {cta}
        <ArrowRightIcon className="size-4 stroke-[2.25]" />
      </a>
    </li>
  );
}
