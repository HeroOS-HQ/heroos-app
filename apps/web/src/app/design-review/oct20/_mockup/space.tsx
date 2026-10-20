import type { ReactNode } from "react";

import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BuildingIcon,
  CertificateIcon,
  ChatIcon,
  CheckCircleIcon,
  CheckIcon,
  ChevronDownIcon,
  ClockIcon,
  PeopleIcon,
  UserIcon,
} from "@/components/site/icons";

import { blueprintHref } from "./blueprint";
import { Backdrop, finalHref, Header } from "./final";
import { COMPANY } from "./scenario";
import { type ExpertAccess, SIGNED_IN, type Space, SPACE_STATES, type SpaceState, spaceFor } from "./space-scenario";

/**
 * Page 3, Company Space: the company's quiet reference page, opened from the
 * account menu. It answers one question: "what do I have in HeroOS, and what
 * should I know about my company here?" It is not a dashboard: no numbers,
 * charts, feeds, tasks or case lists, and no mascot. Ask HeroOS stays the
 * place for any HR question.
 */

const BASE = "/design-review/oct20";

export function spaceHref(state: SpaceState, clean: boolean, anchor?: string | null) {
  const path = state === "full" ? `${BASE}/space` : `${BASE}/space/${state}`;
  return `${path}${clean ? "?clean=1" : ""}${anchor ? `#${anchor}` : ""}`;
}

const quietLink =
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg text-[0.875rem] font-bold text-hero-blue-ink underline-offset-4 hover:underline";
const subheading = "text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted";

function Missing({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-[#8a4a00]">
      <AlertIcon className="size-4 shrink-0" />
      {children}
    </span>
  );
}

/** Marks content that is mock data until JJ confirms it (plan names, limits). */
function MockNote({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-hero-control/80 px-2 py-0.5 text-[0.75rem] font-semibold text-hero-muted">
      {children}
    </span>
  );
}

/** Same rhythm as the Company Blueprint sheet: name and purpose left, details right. */
function Section({ id, icon, title, line, aside, children }: { id: string; icon: ReactNode; title: string; line: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid scroll-mt-6 gap-x-10 gap-y-3 border-t border-hero-border py-6 first:border-t-0 sm:py-7 md:grid-cols-[15.5rem_minmax(0,1fr)]"
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
        {aside ? <div className="mt-2 md:pl-[1.875rem]">{aside}</div> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

/** What an item's availability is, always in words with an icon (never colour alone). */
function Availability({ kind }: { kind: ExpertAccess }) {
  if (kind === "included") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[0.875rem] font-bold text-hero-success">
        <CheckIcon className="size-4" />
        Included
      </span>
    );
  }
  if (kind === "not_included") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[0.875rem] font-semibold text-hero-muted">
        <span aria-hidden="true" className="size-3.5 rounded-full border-2 border-hero-control" />
        Not included
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-hero-control/80 px-2 py-0.5 text-[0.8125rem] font-semibold text-hero-muted">
      <ClockIcon className="size-3.5" />
      To be confirmed
    </span>
  );
}

function Service({
  id,
  icon,
  name,
  line,
  kind,
  children,
}: {
  id?: string;
  icon: ReactNode;
  name: string;
  line: string;
  kind: ExpertAccess;
  children?: ReactNode;
}) {
  return (
    <li className="scroll-mt-6 py-3" id={id}>
      <div className="flex items-start gap-3.5">
        <span aria-hidden="true" className="mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-hero-navy/[0.05] text-hero-navy/70">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="font-bold text-hero-navy">{name}</p>
            <Availability kind={kind} />
          </div>
          <p className="mt-0.5 text-[0.875rem] leading-relaxed text-hero-muted">{line}</p>
          {children}
        </div>
      </div>
    </li>
  );
}

const EXPERT_LINE: Record<ExpertAccess, string> = {
  included: "An HR expert, when a question needs one.",
  not_included: "Not part of your current access. HeroOS still tells you when a question needs an HR expert.",
  unconfirmed: "An HR expert, when a question needs one.",
};

/** Review mode only: says why a value is "To be confirmed" (hidden in the clean, JJ-facing view). */
const UNCONFIRMED_NOTE = "Whether case access includes Expert Review is still to be confirmed.";

function AccessSection({ space, clean }: { space: Space; clean: boolean }) {
  const caseAccess = space.access.kind === "case";
  return (
    <Section
      aside={clean ? null : <MockNote>Mock data · plan names and limits to be confirmed</MockNote>}
      icon={<CertificateIcon className="size-5" />}
      id="access"
      line="What you can use in HeroOS."
      title="Your access"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-[1.5rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy">{space.access.label}</p>
        <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-hero-success-tint px-2.5 text-[0.8125rem] font-bold text-hero-success">
          <CheckIcon className="size-3.5" />
          Active
        </span>
      </div>
      <p className="mt-0.5 text-[0.9375rem] text-hero-muted">{space.access.line}</p>

      {space.includedCase ? (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-hero-navy/10 bg-[#fbfaf8] px-4 py-3">
          <span className="text-[0.875rem] text-hero-muted">Your case</span>
          <a className="font-semibold text-hero-navy underline-offset-4 hover:underline" href={finalHref("warning", clean)}>
            {space.includedCase.title}
          </a>
          <span className="rounded-full bg-hero-blue-tint px-2 py-0.5 text-[0.75rem] font-bold text-hero-blue-ink">{space.includedCase.status}</span>
        </div>
      ) : null}

      <h3 className={`${subheading} mt-5`}>Available to you</h3>
      <ul className="mt-1 divide-y divide-hero-border">
        <Service
          icon={<ChatIcon className="size-[1.125rem]" />}
          kind="included"
          line={caseAccess ? "Guidance for your one case, in your own words." : "Guidance on HR situations, in your own words."}
          name="Ask HeroOS"
        />
        <Service icon={<BuildingIcon className="size-[1.125rem]" />} kind="included" line="The company context HeroOS uses." name="Company Blueprint" />
        <Service icon={<UserIcon className="size-[1.125rem]" />} id="expert-review" kind={space.expert} line={EXPERT_LINE[space.expert]} name="Expert Review">
          {space.expert === "unconfirmed" && !clean ? (
            <p className="mt-1.5">
              <MockNote>{UNCONFIRMED_NOTE}</MockNote>
            </p>
          ) : null}
          {space.expert === "included" ? (
            <details className="group mt-2" open={space.expertOpen}>
              <summary className="inline-flex min-h-8 cursor-pointer list-none items-center gap-1 text-[0.875rem] font-bold text-hero-blue-ink [&::-webkit-details-marker]:hidden">
                How Expert Review works
                <ChevronDownIcon className="size-4 transition-transform duration-200 group-open:rotate-180" />
              </summary>
              <div className="mt-1.5 space-y-2 rounded-xl border border-hero-navy/10 bg-[#fbfaf8] px-4 py-3 text-[0.875rem] leading-relaxed text-hero-navy/85">
                <p>When a question needs a person, HeroOS suggests Expert Review in your conversation. Nothing is sent until you choose Request Expert Review.</p>
                {clean ? null : (
                  <p className="flex flex-wrap items-center gap-2 text-hero-muted">
                    How much is included:
                    <MockNote>To be confirmed</MockNote>
                  </p>
                )}
              </div>
            </details>
          ) : null}
        </Service>
      </ul>

      {caseAccess ? (
        <p className="mt-3 text-[0.875rem] text-hero-muted">
          Need help with another situation?{" "}
          <a className={quietLink} href={spaceHref("limited", clean)}>
            Ask about more access
          </a>
        </p>
      ) : null}
    </Section>
  );
}

export function SpaceWorkspace({ state, clean }: { state: SpaceState; clean: boolean }) {
  const space = spaceFor(state);
  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <Backdrop quiet />
      <Header caseRef={null} clean={clean} menuCurrent="space" state="empty" />

      <main className="relative z-10 min-h-0 flex-1 overflow-y-auto" id="main">
        <div className="mx-auto w-full max-w-[64rem] px-4 pb-14 pt-3 sm:px-8 sm:pt-6">
          <a className="inline-flex min-h-10 items-center gap-1.5 rounded-lg text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:text-hero-navy" href={finalHref("empty", clean)}>
            <ArrowLeftIcon className="size-4" />
            Ask HeroOS
          </a>

          {/* Company identity: concise; details live in the Company Blueprint. */}
          <div className="mt-3 flex items-center gap-4">
            <span aria-hidden="true" className="inline-flex size-14 shrink-0 items-center justify-center rounded-2xl bg-hero-navy text-[1rem] font-extrabold tracking-tight text-white shadow-[0_12px_24px_-14px_rgb(14_30_61/0.8)] sm:size-16 sm:text-[1.125rem]">
              B&amp;B
            </span>
            <div className="min-w-0">
              <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Company Space</p>
              <h1 className="text-[2rem] font-extrabold leading-tight tracking-[-0.035em] text-hero-navy sm:text-[2.5rem]">{COMPANY.name}</h1>
              <p className="text-[0.9375rem] text-hero-muted">
                {space.industry} · {space.jurisdiction ?? <span className="font-semibold text-[#8a4a00]">Jurisdiction not selected</span>}
              </p>
            </div>
          </div>
          <p className="mt-4 text-[1.0625rem] text-hero-muted">Your HeroOS access and company overview.</p>

          <div className="mt-6 rounded-[1.75rem] border border-hero-navy/[0.08] bg-white px-5 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_30px_60px_-40px_rgb(14_30_61/0.35)] sm:px-10">
            <AccessSection clean={clean} space={space} />

            <Section icon={<BuildingIcon className="size-5" />} id="blueprint" line="The context HeroOS uses for your advice." title="Company Blueprint">
              {space.blueprint.complete ? (
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[0.9375rem]">
                  <CheckCircleIcon className="size-5 text-hero-success" />
                  <span className="font-bold text-hero-navy">Complete</span>
                  <span className="text-hero-muted">
                    <span aria-hidden="true">· </span>Last updated {space.blueprint.updated}
                  </span>
                </p>
              ) : (
                <>
                  <p className="pt-1 text-[0.9375rem]">
                    <Missing>
                      {space.blueprint.attention.length} details need attention
                    </Missing>
                  </p>
                  <p className="mt-1 text-[0.9375rem] text-hero-muted">{space.blueprint.attention.join(", ")}</p>
                </>
              )}
              <a
                className={`${quietLink} mt-2`}
                href={space.blueprint.complete ? blueprintHref("review", clean) : blueprintHref("incomplete", clean)}
              >
                {space.blueprint.complete ? "View Company Blueprint" : "Review Blueprint"}
                <ArrowRightIcon className="size-4" />
              </a>
            </Section>

            <Section icon={<PeopleIcon className="size-5" />} id="people" line="Who is using HeroOS." title="People">
              <h3 className={subheading}>Signed in as</h3>
              <div className="mt-2 flex items-center gap-3.5">
                <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-hero-navy text-[0.8125rem] font-extrabold text-white">
                  {SIGNED_IN.initials}
                </span>
                <div className="min-w-0 leading-snug">
                  <p className="font-bold text-hero-navy">{SIGNED_IN.name}</p>
                  <p className="text-[0.875rem] text-hero-muted">
                    <span className="max-sm:block max-sm:truncate">{SIGNED_IN.email}</span>
                    <span aria-hidden="true" className="max-sm:hidden">
                      {" "}
                      ·{" "}
                    </span>
                    <span className="max-sm:block">Primary contact</span>
                  </p>
                </div>
              </div>
              <h3 className={`${subheading} mt-5`}>Other people using HeroOS</h3>
              <p className="mt-1.5 text-[0.9375rem] text-hero-navy">
                {space.others.length > 0 ? (
                  space.others.map((person) => person.name).join(", ")
                ) : (
                  <span className="text-hero-muted">No one else at {COMPANY.name} uses HeroOS yet.</span>
                )}
              </p>
              <a className={`${quietLink} mt-1.5`} href={blueprintHref("review", clean, "people")}>
                People in the Company Blueprint
                <ArrowRightIcon className="size-4" />
              </a>
            </Section>
          </div>

          {/* Ask HeroOS stays the place for any HR question: one quiet reminder, no second home page. */}
          <p className="mt-6 text-center text-[0.9375rem] text-hero-muted">
            Have an HR question?{" "}
            <a className={quietLink} href={finalHref("empty", clean)}>
              Ask HeroOS
              <ArrowRightIcon className="size-4" />
            </a>
          </p>
        </div>
      </main>
    </div>
  );
}

/** The reviewer's controls (not part of the design). `?clean=1` hides them. */
export function SpaceReviewBar({ state, clean }: { state: SpaceState; clean: boolean }) {
  const index = SPACE_STATES.findIndex((s) => s.key === state);
  const prev = SPACE_STATES[(index - 1 + SPACE_STATES.length) % SPACE_STATES.length];
  const next = SPACE_STATES[(index + 1) % SPACE_STATES.length];
  const current = SPACE_STATES[index];
  const pill = "inline-flex h-7 items-center rounded-full px-2.5 font-bold transition-colors duration-150 hover:bg-white/10";
  return (
    <nav aria-label="Design review controls" className="flex h-11 shrink-0 items-center gap-2 bg-[#0b1730] px-2 text-[0.8125rem] text-white sm:gap-3 sm:px-4">
      <a className="font-extrabold text-white" href={BASE}>
        Page 3 · Company Space
      </a>
      <span className="hidden text-white/60 lg:inline">Pages 1–2 approved</span>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        <a aria-label={`Previous state: ${prev.name}`} className={`${pill} px-1.5`} href={spaceHref(prev.key, clean, prev.anchor)}>
          <ArrowLeftIcon className="size-4" />
        </a>
        <p className="min-w-0 truncate">
          <span className="font-extrabold text-hero-yellow">{current.n}</span> <span className="font-semibold">{current.name}</span>
          <span className="hidden text-white/55 md:inline"> · {current.note}</span>
        </p>
        <a aria-label={`Next state: ${next.name}`} className={`${pill} px-1.5`} href={spaceHref(next.key, clean, next.anchor)}>
          <ArrowRightIcon className="size-4" />
        </a>
      </div>
      <a className={`${pill} hidden text-white/80 sm:inline-flex`} href={spaceHref(state, true, current.anchor)}>
        Hide bar
      </a>
    </nav>
  );
}

export function SpaceScreen({ state, clean }: { state: SpaceState; clean: boolean }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {clean ? null : <SpaceReviewBar clean={clean} state={state} />}
      <SpaceWorkspace clean={clean} state={state} />
    </div>
  );
}
