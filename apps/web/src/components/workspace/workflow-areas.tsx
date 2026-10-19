import type { ReactNode } from "react";

import { ChevronRightIcon, ClockIcon, DocumentIcon, LockIcon, PeopleIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import type { Blueprint } from "@/lib/server/heroos-api";
import type { Tone } from "@/lib/workflows/copy";

export type WorkflowKey = "disciplinary" | "probation" | "recruitment";

/** The three V1 HR workflows, in the order JJ's HR Services screen shows them. */
export const WORKFLOWS: { key: WorkflowKey; title: string; description: string; icon: (className: string) => ReactNode }[] = [
  {
    key: "disciplinary",
    title: "Conduct & Discipline",
    description: "Record conduct concerns and handle disciplinary cases fairly and consistently, step by step.",
    icon: (className) => <DocumentIcon className={className} />,
  },
  {
    key: "probation",
    title: "Probation",
    description: "Support for reviewing a new hire's probation period and recording the outcome.",
    icon: (className) => <ClockIcon className={className} />,
  },
  {
    key: "recruitment",
    title: "Recruitment",
    description: "A structured path from defining a role to making an offer.",
    icon: (className) => <PeopleIcon className={className} />,
  },
];

export type Availability = {
  /** Status in words (never colour alone). */
  label: string;
  /** The same, in a word or two, for compact lists. */
  short: string;
  tone: Tone;
  detail: string;
  /** Where it opens; null when there is nothing to open for this account. */
  href: string | null;
};

/** Guidance may use the Company's jurisdiction only when the API confirmed it. */
export const jurisdictionConfirmed = (blueprint: Blueprint | null) =>
  blueprint !== null && blueprint.jurisdiction.readiness === "supported_confirmed" && blueprint.jurisdiction.guidanceAllowed;

/**
 * What each workflow offers this account today. Disciplinary opens for
 * Company administrators (intake, records and history; steps and previews
 * where approved rules and templates are installed); for other members it is
 * administrator-only, with no link. The others are honestly not available
 * yet: no links, nothing that suggests a working feature. The API enforces
 * access whatever this shows.
 */
export function workflowAvailability(
  key: WorkflowKey,
  { companyId, admin, blueprint }: { companyId: string; admin: boolean; blueprint: Blueprint | null },
): Availability {
  if (key !== "disciplinary") {
    return {
      label: "Coming soon",
      short: "Coming soon",
      tone: "muted",
      detail: "Not available yet. It will appear here when it's ready.",
      href: null,
    };
  }
  if (!admin) {
    return {
      label: "Administrators only",
      short: "Administrators only",
      tone: "muted",
      detail: "Disciplinary cases are confidential: only your company's administrators can open them.",
      href: null,
    };
  }
  const href = `/workspaces/${encodeURIComponent(companyId)}/disciplinary`;
  return jurisdictionConfirmed(blueprint)
    ? {
        label: "In development",
        short: "In development",
        tone: "neutral",
        detail: "Guided intake, your decision records and the case history.",
        href,
      }
    : {
        label: "Limited until jurisdiction is confirmed",
        short: "Limited",
        tone: "caution",
        detail: "You can create and record cases; jurisdiction-specific steps wait for confirmation.",
        href,
      };
}

/**
 * The HR workflows as a compact list (the dashboard's "HR services" card): each
 * with its availability in words, and a link only where there is something to
 * open.
 */
export function WorkflowAreas({
  companyId,
  admin,
  blueprint,
  className,
}: {
  companyId: string;
  admin: boolean;
  blueprint: Blueprint | null;
  className?: string;
}) {
  return (
    <section aria-labelledby="workflows-heading" className={className}>
      <div className="flex items-center gap-3">
        <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-hero-bg text-hero-navy">
          <DocumentIcon className="size-5" />
        </span>
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="workflows-heading">
          HR services
        </h2>
      </div>
      <ul className="mt-3 flex flex-col">
        {WORKFLOWS.map((workflow) => {
          const availability = workflowAvailability(workflow.key, { companyId, admin, blueprint });
          const body = (
            <>
              <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-hero-bg text-hero-navy">
                {availability.href ? workflow.icon("size-5") : <LockIcon className="size-5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[0.9375rem] font-bold text-hero-navy">{workflow.title}</span>
                  <StatusBadge tone={availability.tone}>{availability.short}</StatusBadge>
                </span>
                <span className="mt-0.5 block text-sm leading-snug text-hero-muted">{availability.detail}</span>
              </span>
            </>
          );
          return (
            <li className="border-t border-hero-border first:border-t-0" key={workflow.key}>
              {availability.href ? (
                <a
                  className="group -mx-2 flex items-center gap-3 rounded-xl px-2 py-3 transition-colors duration-150 hover:bg-hero-blue-tint/50"
                  href={availability.href}
                >
                  {body}
                  <ChevronRightIcon className="size-5 shrink-0 text-hero-blue-ink transition-transform duration-150 group-hover:translate-x-0.5" />
                </a>
              ) : (
                <div className="flex items-center gap-3 py-3">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
