import type { ReactNode } from "react";

import { PersonAvatar, quietLink, sheet } from "@/components/app/workspace-chrome";
import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BuildingIcon,
  CertificateIcon,
  ChatIcon,
  CheckCircleIcon,
  CheckIcon,
  ClockIcon,
  LockIcon,
  PeopleIcon,
  UserIcon,
} from "@/components/site/icons";
import { attentionOf, jurisdictionDisplay } from "@/lib/blueprint/model";
import { roleLabel } from "@/lib/onboarding/copy";
import type { WorkspaceDetails } from "@/lib/server/heroos-api";
import { formatDay } from "@/lib/workflows/copy";

/**
 * Page 3, Company Space (approved Oct 20 design): the company's quiet
 * reference page. It answers "what do I have in HeroOS, and what should I know
 * about my company here?" Not a dashboard: no numbers, charts, feeds, tasks or
 * case lists. Everything on it is the API's answer for this account: the
 * Company, the account's role and the Blueprint. HeroOS has no plans, limits
 * or entitlements yet (M2-NEW-10), so none are shown; where something isn't
 * decided, the page says so.
 */

type Availability = "included" | "view_only" | "admins_only" | "unconfirmed";

function Missing({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-[#8a4a00]">
      <AlertIcon className="size-4 shrink-0" />
      {children}
    </span>
  );
}

/** Same rhythm as the Company Blueprint sheet: name and purpose left, details right. */
function Section({ id, icon, title, line, children }: { id: string; icon: ReactNode; title: string; line: string; children: ReactNode }) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid scroll-mt-24 gap-x-10 gap-y-3 border-t border-hero-border py-6 first:border-t-0 sm:py-7 md:grid-cols-[15.5rem_minmax(0,1fr)]"
      id={id}
    >
      <div>
        <div className="flex items-center gap-2.5">
          <span className="text-hero-muted">{icon}</span>
          <h2 className="text-[1.0625rem] font-extrabold tracking-[-0.01em] text-hero-navy" id={`${id}-title`}>
            {title}
          </h2>
        </div>
        <p className="mt-1 text-[0.875rem] leading-relaxed text-hero-muted md:pl-[1.875rem]">{line}</p>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

/** What an item's availability is, always in words with an icon (never colour alone). */
function AvailabilityTag({ kind }: { kind: Availability }) {
  switch (kind) {
    case "included":
      return (
        <span className="inline-flex items-center gap-1.5 text-[0.875rem] font-bold text-hero-success">
          <CheckIcon className="size-4" />
          Included
        </span>
      );
    case "view_only":
      return (
        <span className="inline-flex items-center gap-1.5 text-[0.875rem] font-semibold text-hero-muted">
          <CheckIcon className="size-4" />
          View only
        </span>
      );
    case "admins_only":
      return (
        <span className="inline-flex items-center gap-1.5 text-[0.875rem] font-semibold text-hero-muted">
          <LockIcon className="size-3.5" />
          Administrators only
        </span>
      );
    case "unconfirmed":
      return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-hero-control/80 px-2 py-0.5 text-[0.8125rem] font-semibold text-hero-muted">
          <ClockIcon className="size-3.5" />
          To be confirmed
        </span>
      );
  }
}

function Service({ icon, name, line, kind }: { icon: ReactNode; name: string; line: string; kind: Availability }) {
  return (
    <li className="py-3">
      <div className="flex items-start gap-3.5">
        <span aria-hidden="true" className="mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-hero-navy/[0.05] text-hero-navy/70">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="font-bold text-hero-navy">{name}</p>
            <AvailabilityTag kind={kind} />
          </div>
          <p className="mt-0.5 text-[0.875rem] leading-relaxed text-hero-muted">{line}</p>
        </div>
      </div>
    </li>
  );
}

/** "Bush & Bush" → "B&B"; at most three characters. */
export function monogram(name: string): string {
  const tokens = name
    .replace(/[^\p{L}\p{N}&\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const letters = tokens.map((token) => (token === "&" ? "&" : token[0].toUpperCase())).join("");
  return letters.slice(0, 3) || "·";
}

export function SpacePage({ details }: { details: WorkspaceDetails }) {
  const { company, membership, blueprint } = details;
  const base = `/workspaces/${encodeURIComponent(company.id)}`;
  const admin = membership?.role === "company_admin";
  const role = roleLabel(membership?.role ?? null);
  const jurisdiction = blueprint ? jurisdictionDisplay(blueprint) : null;
  const attention = blueprint ? attentionOf(blueprint) : [];

  return (
    <div className="mx-auto w-full max-w-[64rem] px-4 pb-14 pt-3 sm:px-8 sm:pt-6">
      <a
        className="inline-flex min-h-10 items-center gap-1.5 rounded-lg text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:text-hero-navy max-sm:min-h-11"
        href={base}
      >
        <ArrowLeftIcon className="size-4" />
        Ask HeroOS
      </a>

      {/* Company identity: concise; details live in the Company Blueprint. */}
      <div className="mt-3 flex items-center gap-4">
        <span
          aria-hidden="true"
          className="inline-flex size-14 shrink-0 items-center justify-center rounded-2xl bg-hero-navy text-[1rem] font-extrabold tracking-tight text-white shadow-[0_12px_24px_-14px_rgb(14_30_61/0.8)] sm:size-16 sm:text-[1.125rem]"
        >
          {monogram(company.name)}
        </span>
        <div className="min-w-0">
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Company Space</p>
          <h1 className="break-words text-[2rem] font-extrabold leading-tight tracking-[-0.035em] text-hero-navy sm:text-[2.5rem]">
            {company.name}
          </h1>
          <p className="text-[0.9375rem] text-hero-muted">
            {blueprint?.industry ?? "Industry not added"} ·{" "}
            {jurisdiction === null || jurisdiction.kind === "missing" ? (
              <span className="font-semibold text-[#8a4a00]">Jurisdiction not selected</span>
            ) : (
              jurisdiction.label
            )}
          </p>
        </div>
      </div>
      <p className="mt-4 text-[1.0625rem] text-hero-muted">Your HeroOS access and company overview.</p>

      <div className={`mt-6 ${sheet}`}>
        <Section icon={<CertificateIcon className="size-5" />} id="access" line="What you can use in HeroOS." title="Your access">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <p className="text-[1.5rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy">
              {admin ? "Company administrator" : (role ?? "Member")}
            </p>
            <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-hero-success-tint px-2.5 text-[0.8125rem] font-bold text-hero-success">
              <CheckIcon className="size-3.5" />
              Active
            </span>
          </div>
          <p className="mt-0.5 text-[0.9375rem] text-hero-muted">
            {admin
              ? "You can ask HeroOS, open cases and keep the Company Blueprint up to date."
              : "You can see the Company Blueprint. Cases are for company administrators for now."}
          </p>
          <h3 className="mt-5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Available to you</h3>
          <ul className="mt-1 divide-y divide-hero-border">
            <Service
              icon={<ChatIcon className="size-[1.125rem]" />}
              kind={admin ? "included" : "admins_only"}
              line="Guidance on HR situations, in your own words."
              name="Ask HeroOS"
            />
            <Service
              icon={<BuildingIcon className="size-[1.125rem]" />}
              kind={membership?.canUpdateBlueprint ? "included" : "view_only"}
              line="The company context HeroOS uses."
              name="Company Blueprint"
            />
            <Service
              icon={<UserIcon className="size-[1.125rem]" />}
              kind="unconfirmed"
              line="When a case needs a specialist, HeroOS says so. Requesting Expert Review in HeroOS isn't available yet."
              name="Expert Review"
            />
          </ul>
        </Section>

        <Section icon={<BuildingIcon className="size-5" />} id="blueprint" line="The context HeroOS uses for your advice." title="Company Blueprint">
          {blueprint === null ? (
            <p className="pt-1 text-[0.9375rem] text-hero-muted">The Company Blueprint isn&apos;t available here yet.</p>
          ) : attention.length === 0 ? (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[0.9375rem]">
              <CheckCircleIcon className="size-5 text-hero-success" />
              <span className="font-bold text-hero-navy">Complete</span>
              {blueprint.updatedAt ? (
                <span className="text-hero-muted">
                  <span aria-hidden="true">· </span>Last updated <time dateTime={blueprint.updatedAt}>{formatDay(blueprint.updatedAt)}</time>
                </span>
              ) : null}
            </p>
          ) : (
            <>
              <p className="pt-1 text-[0.9375rem]">
                <Missing>{attention.length === 1 ? "1 detail needs attention" : `${attention.length} details need attention`}</Missing>
              </p>
              <p className="mt-1 text-[0.9375rem] text-hero-muted">{attention.map((item) => item.label).join(", ")}</p>
            </>
          )}
          {blueprint !== null ? (
            <a className={`${quietLink} mt-2`} href={`${base}/settings`}>
              {attention.length === 0 ? "View Company Blueprint" : "Review Blueprint"}
              <ArrowRightIcon className="size-4" />
            </a>
          ) : null}
        </Section>

        <Section icon={<PeopleIcon className="size-5" />} id="people" line="Who is using HeroOS." title="People">
          <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Signed in as</h3>
          <div className="mt-2 flex items-center gap-3.5">
            <PersonAvatar className="size-10" />
            <div className="min-w-0 leading-snug">
              <p className="font-bold text-hero-navy">You</p>
              {role ? <p className="text-[0.875rem] text-hero-muted">{admin ? "Company administrator" : role}</p> : null}
            </div>
          </div>
          <h3 className="mt-5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">Other people using HeroOS</h3>
          <p className="mt-1.5 text-[0.9375rem] text-hero-muted">HeroOS can&apos;t list the other people in your company here yet.</p>
        </Section>
      </div>

      {/* Ask HeroOS stays the place for any HR question: one quiet reminder, no second home page. */}
      <p className="mt-6 text-center text-[0.9375rem] text-hero-muted">
        Have an HR question?{" "}
        <a className={quietLink} href={base}>
          Ask HeroOS
          <ArrowRightIcon className="size-4" />
        </a>
      </p>
    </div>
  );
}
