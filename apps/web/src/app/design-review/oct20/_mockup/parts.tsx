import type { ReactNode } from "react";

import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  CloseIcon,
  DocumentIcon,
  HelpIcon,
  InfoIcon,
  LightbulbIcon,
  PeopleIcon,
  SearchIcon,
  SendIcon,
} from "@/components/site/icons";

import {
  ATTENDANCE_STATUS,
  CASE_STATUS,
  CASES,
  type CaseRef,
  type CaseStatus,
  COMPANY,
  type Direction,
  DIRECTION_NAMES,
  type HeroTurn,
  PERSON,
  type StateKey,
  STATES,
  type Tone,
  type Turn,
} from "./scenario";

/* ------------------------------------------------------------------ links */

export type LinkOpts = { clean: boolean; rail: boolean };

export function stateHref(direction: Direction, state: StateKey, opts: LinkOpts, extra?: Partial<LinkOpts>) {
  const merged = { ...opts, ...extra };
  const query = new URLSearchParams();
  if (merged.clean) query.set("clean", "1");
  if (!merged.rail) query.set("rail", "0");
  const search = query.toString();
  return `/design-review/oct20/archive/${direction}/${state}${search ? `?${search}` : ""}`;
}

/** Where the prototype's main action leads from each state (Send, a quick reply). */
export const NEXT: Record<StateKey, StateKey> = {
  empty: "typing",
  typing: "understanding",
  understanding: "conversation",
  conversation: "warning",
  warning: "block",
  block: "status",
  expert: "history",
  status: "history",
  history: "reopened",
  reopened: "conversation",
};

/** The state that shows each case (the history list links here). */
export const CASE_STATE: Partial<Record<string, StateKey>> = {
  attendance: "warning",
  staffing: "expert",
  probation: "reopened",
};

/** Hidden fields so Send (a plain GET form) keeps the review options. */
export function hiddenFields(opts: LinkOpts): [string, string][] {
  return [...(opts.clean ? ([["clean", "1"]] as [string, string][]) : []), ...(!opts.rail ? ([["rail", "0"]] as [string, string][]) : [])];
}

/* ----------------------------------------------------------------- shared */

export const ink = "text-hero-navy";
export const iconButton =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full px-2.5 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-navy/[0.06]";

/** HeroOS speaking: the approved speech-bubble symbol. */
export function HeroOSAvatar({ breathe = false, size = "md" }: { breathe?: boolean; size?: "md" | "lg" }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-[0.6rem] bg-white ring-1 ring-hero-border ${
        size === "lg" ? "size-10" : "size-7"
      } ${breathe ? "dr-breathe" : ""}`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className={size === "lg" ? "h-[1.15rem] w-auto" : "h-[0.85rem] w-auto"}
        height={144}
        src="/branding/heroos-logo-symbol.png"
        width={212}
      />
    </span>
  );
}

/** A stop sign drawn with CSS (no new icon file): octagon with a bar. */
function StopGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center bg-current [clip-path:polygon(29%_0,71%_0,100%_29%,100%_71%,71%_100%,29%_100%,0_71%,0_29%)] ${className ?? "size-4"}`}
    >
      <span className="h-[2px] w-[55%] rounded bg-white" />
    </span>
  );
}

export const TONE: Record<Tone, { label: string; icon: (className: string) => ReactNode }> = {
  guidance: { label: "Guidance", icon: (c) => <LightbulbIcon className={c} /> },
  warning: { label: "Warning", icon: (c) => <AlertIcon className={c} /> },
  stop: { label: "Stop", icon: (c) => <StopGlyph className={c} /> },
  expert: { label: "Expert Review", icon: (c) => <PeopleIcon className={c} /> },
};

export function ToneLabel({ tone }: { tone: Tone }) {
  return (
    <span
      className={`tone-${tone} inline-flex h-6 items-center gap-1.5 rounded-full bg-(--tone-chip) px-2.5 text-[0.75rem] font-bold tracking-[0.01em] text-(--tone-ink)`}
    >
      {TONE[tone].icon("size-3.5")}
      {TONE[tone].label}
      {tone === "stop" ? <span className="max-sm:hidden"> · HeroOS can&apos;t proceed</span> : null}
    </span>
  );
}

export function StatusChip({ status, compact = false }: { status: CaseStatus; compact?: boolean }) {
  const s = CASE_STATUS[status];
  return (
    <span className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border border-hero-border bg-white px-2.5 text-[0.8125rem] font-semibold text-hero-navy">
      <span aria-hidden="true" className={`size-2 rounded-full ${s.dot}`} />
      <span className={compact ? "max-sm:sr-only" : ""}>{s.label}</span>
    </span>
  );
}

/** A labelled stand-in for something JJ still has to confirm (never invented content). */
export function Pending({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-hero-control px-2 py-0.5 text-[0.75rem] font-semibold text-hero-muted">
      <span className="rounded bg-hero-navy px-1 text-[0.625rem] font-bold uppercase tracking-wide text-white">JJ</span>
      {children}
    </span>
  );
}

/** A very quiet skyline along the bottom of the Ask page: brand light blue, decorative. */
export function Skyline({ className }: { className: string }) {
  const heights = [
    "h-[22%] w-10", "h-[34%] w-6", "h-[28%] w-9", "h-[44%] w-5", "h-[26%] w-11", "h-[38%] w-7", "h-[30%] w-8",
    "h-[50%] w-6", "h-[24%] w-10", "h-[36%] w-7",
  ];
  return (
    <div aria-hidden="true" className={`pointer-events-none ${className}`}>
      <div className="absolute inset-x-0 bottom-0 flex h-full items-end justify-center gap-[0.35rem] [mask-image:linear-gradient(90deg,transparent_0%,black_25%,black_75%,transparent_100%)]">
        {heights.slice(0, 5).map((size, index) => (
          <span className={`rounded-t-md bg-hero-light-blue/[0.06] ${size}`} key={`l${index}`} />
        ))}
        <span className="h-full w-7 bg-hero-light-blue/[0.1] [clip-path:polygon(47%_0,53%_0,64%_38%,78%_62%,100%_100%,0_100%,22%_62%,36%_38%)]" />
        {heights.slice(5).map((size, index) => (
          <span className={`rounded-t-md bg-hero-light-blue/[0.06] ${size}`} key={`r${index}`} />
        ))}
        {heights.slice(0, 4).map((size, index) => (
          <span className={`rounded-t-md bg-hero-light-blue/[0.05] ${size}`} key={`e${index}`} />
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------- conversation */

function UserTurnView({ text, at }: { text: string; at: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[88%] sm:max-w-[78%]">
        <p className="sr-only">You said:</p>
        <p className="rounded-[1.25rem] rounded-br-md border border-hero-border bg-white px-4 py-3 text-[0.96875rem] leading-[1.6] text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.05)]">
          {text}
        </p>
        <p className="mt-1 pr-1 text-right text-xs tabular-nums text-hero-muted">{at}</p>
      </div>
    </div>
  );
}

function Chips({ items, href }: { items: string[]; href: string }) {
  return (
    <ul aria-label="Quick replies" className="mt-3 flex flex-wrap gap-2">
      {items.map((item) => (
        <li key={item}>
          <a
            className="inline-flex min-h-10 items-center rounded-full border border-(--tone-line) bg-white px-4 text-[0.875rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-(--tone-chip)"
            href={href}
          >
            {item}
          </a>
        </li>
      ))}
    </ul>
  );
}

function NumberedList({ items }: { items: string[] }) {
  return (
    <ol className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li className="flex gap-2.5" key={item}>
          <span
            aria-hidden="true"
            className="mt-[0.2rem] inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-(--tone-chip) text-[0.6875rem] font-extrabold text-(--tone-ink)"
          >
            {index + 1}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

const boxHeading = "text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)";

function HeroTurnView({ turn, latest, nextHref }: { turn: HeroTurn; latest: boolean; nextHref: string }) {
  const nameId = `turn-${turn.id}`;
  return (
    <article
      aria-labelledby={nameId}
      className={`tone-${turn.tone} relative overflow-hidden rounded-[1.25rem] border border-(--tone-line) bg-(--tone-bg) px-4 py-4 sm:px-5 sm:py-5 ${
        turn.tone === "guidance" ? "" : "shadow-[0_10px_30px_-22px_rgb(14_30_61/0.45)]"
      }`}
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-(--tone-rail)" />
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
        <HeroOSAvatar />
        <h3 className="text-[0.9375rem] font-extrabold text-hero-navy" id={nameId}>
          HeroOS<span className="sr-only">, {TONE[turn.tone].label}</span>
        </h3>
        <ToneLabel tone={turn.tone} />
        <time className="ml-auto text-xs tabular-nums text-hero-muted">{turn.at}</time>
      </header>

      <div className="mt-3 space-y-3 text-[0.96875rem] leading-[1.65] text-hero-navy sm:pl-[2.375rem]">
        {turn.lead ? <p className={turn.title ? "text-hero-muted" : ""}>{turn.lead}</p> : null}
        {turn.title ? (
          <p className="text-[1.125rem] font-extrabold leading-snug tracking-[-0.01em] text-(--tone-ink)">{turn.title}</p>
        ) : null}
        {turn.body?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}

        {turn.steps ? (
          <div className="rounded-xl border border-(--tone-line) bg-white/75 px-4 py-3">
            <p className={boxHeading}>{turn.steps.heading}</p>
            {turn.steps.items.length > 1 ? (
              <NumberedList items={turn.steps.items} />
            ) : (
              <p className="mt-1.5 flex gap-2">
                <ArrowRightIcon className="mt-[0.3rem] size-4 shrink-0 text-(--tone-rail)" />
                {turn.steps.items[0]}
              </p>
            )}
          </div>
        ) : null}

        {turn.next || turn.provide ? (
          <div className="grid gap-3 md:grid-cols-[1.35fr_1fr]">
            {turn.next ? (
              <div className="rounded-xl border border-(--tone-line) bg-white/80 px-4 py-3">
                <p className={boxHeading}>{turn.next.heading}</p>
                <NumberedList items={turn.next.items} />
              </div>
            ) : null}
            {turn.provide ? (
              <div className="rounded-xl border border-(--tone-line) bg-white/80 px-4 py-3">
                <p className={boxHeading}>{turn.provide.heading}</p>
                <ul className="mt-2 space-y-1.5">
                  {turn.provide.items.map((item) => (
                    <li className="flex gap-2" key={item}>
                      <CheckIcon className="mt-[0.3rem] size-4 shrink-0 text-(--tone-rail)" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        {turn.plan ? (
          <div className="flex gap-2 text-[0.875rem] leading-relaxed text-hero-navy/85">
            <InfoIcon className="mt-[0.2rem] size-4 shrink-0 text-(--tone-rail)" />
            <p>
              {turn.plan} <Pending>Plan allowance and wording</Pending>
            </p>
          </div>
        ) : null}

        {turn.question ? (
          <div className="rounded-xl bg-white px-4 py-3 ring-1 ring-(--tone-line)">
            <p className="flex items-center gap-1.5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">
              <HelpIcon className="size-3.5" />
              HeroOS needs to know
            </p>
            <p className="mt-1 font-semibold leading-snug">{turn.question}</p>
            {latest && turn.chips ? <Chips href={nextHref} items={turn.chips} /> : null}
          </div>
        ) : null}

        {turn.actions ? (
          <div>
            {turn.tone === "stop" ? <p className={boxHeading}>What you can do instead</p> : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {turn.actions.map((action) => (
                <a
                  className={
                    action.primary
                      ? "inline-flex min-h-11 items-center gap-2 rounded-full bg-(--tone-rail) px-5 text-[0.9375rem] font-bold text-white shadow-[0_8px_18px_-10px_rgb(169_47_108/0.8)] transition-transform duration-150 hover:-translate-y-px"
                      : "inline-flex min-h-11 items-center gap-2 rounded-full border border-(--tone-line) bg-white px-4 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-(--tone-chip)"
                  }
                  href={nextHref}
                  key={action.label}
                >
                  {action.primary ? <PeopleIcon className="size-4" /> : null}
                  {action.label}
                </a>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {turn.considered ? (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-hero-muted sm:pl-[2.375rem]">
          <span className="font-semibold">Considered:</span>
          {turn.considered.map((item) => (
            <span className="inline-flex items-center gap-1" key={item}>
              <CheckIcon className="size-3.5 text-(--tone-rail)" />
              {item}
            </span>
          ))}
        </p>
      ) : null}
    </article>
  );
}

function Divider({ text, strong = false }: { text: string; strong?: boolean }) {
  return (
    <div className="flex items-center gap-3 py-1" role="separator">
      <span className="h-px flex-1 bg-hero-border" />
      <span className={`text-[0.8125rem] ${strong ? "font-bold text-hero-blue-ink" : "font-semibold text-hero-muted"}`}>{text}</span>
      <span className="h-px flex-1 bg-hero-border" />
    </div>
  );
}

/** "HeroOS is looking at your situation": shown between Send and the first answer. */
export function ThinkingTurn() {
  const steps = [
    "Reading what happened",
    `Checking your Company Blueprint and ${COMPANY.jurisdiction} jurisdiction`,
    "Opening and naming your case",
  ];
  return (
    <div className="flex items-start gap-3 rounded-[1.25rem] border border-dashed border-hero-control/70 bg-white/70 px-4 py-4 sm:px-5" role="status">
      <HeroOSAvatar breathe size="lg" />
      <div className="min-w-0">
        <p className="text-[0.9375rem] font-extrabold leading-snug text-hero-navy">
          HeroOS <span className="font-medium text-hero-muted">is looking at your situation</span>
          <span aria-hidden="true" className="ml-2 inline-flex gap-1 align-middle">
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
          </span>
        </p>
        <ul className="mt-2.5 space-y-1.5 text-[0.875rem] text-hero-navy/85">
          {steps.map((step) => (
            <li className="dr-step flex items-center gap-2" key={step}>
              <CheckIcon className="size-4 shrink-0 text-hero-success" />
              {step}
            </li>
          ))}
          <li className="dr-step flex items-center gap-2 font-semibold text-hero-navy">
            <span aria-hidden="true" className="dr-ring ml-1 mr-0.5 size-2 rounded-full bg-hero-blue" />
            Working out what to ask you first
          </li>
        </ul>
      </div>
    </div>
  );
}

export function ConversationLog({
  turns,
  thinking = false,
  nextHref,
  label,
}: {
  turns: Turn[];
  thinking?: boolean;
  nextHref: string;
  label: string;
}) {
  const lastHero = [...turns].reverse().find((turn) => turn.kind === "hero");
  return (
    <ol aria-label={label} className="flex flex-col gap-5" role="log">
      {turns.map((turn, index) => (
        <li className={index === turns.length - 1 ? "dr-rise" : ""} key={turn.id}>
          {turn.kind === "user" ? (
            <UserTurnView at={turn.at} text={turn.text} />
          ) : turn.kind === "hero" ? (
            <HeroTurnView latest={turn === lastHero} nextHref={nextHref} turn={turn} />
          ) : turn.kind === "divider" ? (
            <Divider strong={turn.text.startsWith("You left")} text={turn.text} />
          ) : (
            <p className="text-center">
              <a className="inline-flex min-h-9 items-center rounded-full bg-hero-navy/[0.05] px-3.5 text-[0.8125rem] font-semibold text-hero-muted hover:bg-hero-navy/[0.08]" href={nextHref}>
                Show {turn.text}
              </a>
            </p>
          )}
        </li>
      ))}
      {thinking ? (
        <li className="dr-rise-late">
          <ThinkingTurn />
        </li>
      ) : null}
    </ol>
  );
}

/* --------------------------------------------------------------- composer */

export function Composer({
  variant,
  action,
  hidden,
  value,
  disabled = false,
}: {
  variant: "ask" | "reply";
  action: string;
  hidden: [string, string][];
  value?: string;
  disabled?: boolean;
}) {
  const ask = variant === "ask";
  const id = ask ? "ask-heroos" : "reply-heroos";
  return (
    <form action={action.split("?")[0]} method="get">
      {hidden.map(([name, val]) => (
        <input key={name} name={name} type="hidden" value={val} />
      ))}
      <div
        className={`dr-composer rounded-[1.6rem] border border-hero-control/55 bg-white shadow-[0_1px_2px_rgb(14_30_61/0.04),0_20px_44px_-26px_rgb(14_30_61/0.35)] transition-[border-color,box-shadow] duration-200 focus-within:border-hero-blue focus-within:shadow-[0_0_0_4px_rgb(61_107_196/0.13),0_20px_44px_-26px_rgb(14_30_61/0.35)] ${
          disabled ? "opacity-70" : ""
        }`}
      >
        <label className="sr-only" htmlFor={id}>
          {ask ? "Describe your HR situation in your own words" : "Reply to HeroOS"}
        </label>
        <textarea
          className={`block w-full resize-none bg-transparent px-5 text-hero-navy placeholder:text-hero-muted/90 focus-visible:outline-none ${
            ask ? "min-h-[6.5rem] pt-4 text-[1.0625rem] leading-relaxed sm:min-h-[7.5rem]" : "min-h-[3.25rem] pt-3.5 text-base leading-relaxed"
          }`}
          defaultValue={value}
          disabled={disabled}
          id={id}
          placeholder={
            disabled
              ? "HeroOS is looking at your situation…"
              : ask
                ? "Describe what's happening, in your own words…"
                : "Reply to HeroOS…"
          }
          rows={ask ? 3 : 1}
        />
        <div className="flex items-center gap-2 px-3 pb-3">
          {ask ? (
            <p className="pl-2 text-[0.8125rem] text-hero-muted max-sm:sr-only">
              Example: <span className="italic">“One of my team hasn&apos;t come in for two days.”</span>
            </p>
          ) : (
            <button
              className="inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:bg-hero-navy/[0.05] hover:text-hero-navy"
              disabled={disabled}
              type="button"
            >
              <DocumentIcon className="size-[1.125rem]" />
              <span className="max-sm:sr-only">Add a document</span>
            </button>
          )}
          <button
            aria-label="Send"
            className="dr-send ml-auto inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-hero-navy text-white shadow-[0_8px_18px_-10px_rgb(14_30_61/0.9)] transition-[background-color,transform] duration-150 hover:-translate-y-px hover:bg-[#182c55]"
            disabled={disabled}
            type="submit"
          >
            <SendIcon className="size-5" />
          </button>
        </div>
      </div>
      {ask ? (
        <p aria-live="polite" className="dr-typing-hint mt-2.5 text-center text-[0.875rem] font-medium text-hero-blue-ink">
          No category or title needed. HeroOS opens and names the case for you.
        </p>
      ) : null}
    </form>
  );
}

/** The quiet line under the Ask composer: what HeroOS uses, and who decides. */
export function TrustLine({ className = "" }: { className?: string }) {
  return (
    <p className={`flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[0.8125rem] text-hero-muted ${className}`}>
      <span className="inline-flex items-center gap-1">
        <CheckIcon className="size-3.5 text-hero-blue" />
        Uses your Company Blueprint
      </span>
      <span className="inline-flex items-center gap-1">
        <CheckIcon className="size-3.5 text-hero-blue" />
        Jurisdiction: {COMPANY.jurisdiction}
      </span>
      <span className="max-sm:hidden">· HeroOS advises; you decide</span>
    </p>
  );
}

/* ------------------------------------------------------------ case status */

const journeyMarker: Record<string, string> = {
  done: "bg-hero-navy text-white",
  guidance: "tone-guidance bg-(--tone-chip) text-(--tone-ink)",
  warning: "tone-warning bg-(--tone-chip) text-(--tone-ink)",
  current: "dr-ring bg-white text-hero-blue ring-2 ring-hero-blue",
};

export function CaseStatusBody({ closeHref, caseRef, idPrefix = "cs" }: { closeHref: string; caseRef: CaseRef; idPrefix?: string }) {
  const s = ATTENDANCE_STATUS;
  const id = (name: string) => `${idPrefix}-${name}`;
  return (
    <div className="flex flex-col">
      <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-hero-border bg-white/95 px-5 pb-4 pt-5 backdrop-blur">
        <div className="min-w-0 flex-1">
          <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Case status</p>
          <h2 className="mt-1 text-[1.25rem] font-extrabold leading-tight tracking-[-0.015em] text-hero-navy" id={id("title")}>
            {caseRef.title}
          </h2>
          <p className="mt-1 text-[0.8125rem] text-hero-muted">Named by HeroOS · Opened today, 09:12</p>
        </div>
        <a aria-label="Close case status" className={`${iconButton} -mr-2 -mt-1`} href={closeHref}>
          <CloseIcon className="size-5" />
        </a>
      </div>

      <div className="space-y-6 px-5 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={caseRef.status} />
        </div>
        <section aria-labelledby={id("where")}>
          <h3 className="text-[0.9375rem] font-extrabold text-hero-navy" id={id("where")}>
            Where things stand
          </h3>
          <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-hero-navy/85">{s.summary}</p>
        </section>

        <section aria-labelledby={id("next")} className="tone-guidance rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5">
          <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)" id={id("next")}>
            Your next step
          </h3>
          <p className="mt-1 text-[0.9375rem] font-semibold leading-snug text-hero-navy">{s.nextStep}</p>
        </section>

        <section aria-labelledby={id("journey")}>
          <h3 className="text-[0.9375rem] font-extrabold text-hero-navy" id={id("journey")}>
            How the case has gone
          </h3>
          <ol className="relative mt-3 space-y-4 before:absolute before:bottom-3 before:left-[0.6875rem] before:top-2 before:w-px before:bg-hero-border">
            {s.journey.map((step) => (
              <li className="relative flex gap-3" key={step.title}>
                <span
                  aria-hidden="true"
                  className={`relative z-10 mt-0.5 inline-flex size-[1.375rem] shrink-0 items-center justify-center rounded-full ${journeyMarker[step.tone]}`}
                >
                  {step.tone === "done" ? <CheckIcon className="size-3" /> : null}
                  {step.tone === "guidance" ? <LightbulbIcon className="size-3" /> : null}
                  {step.tone === "warning" ? <AlertIcon className="size-3" /> : null}
                  {step.tone === "current" ? <span className="size-2 rounded-full bg-hero-blue" /> : null}
                </span>
                <div className="min-w-0">
                  <p className={`text-[0.9375rem] leading-snug ${step.tone === "current" ? "font-extrabold text-hero-blue-ink" : "font-bold text-hero-navy"}`}>
                    {step.title}
                    <span className="ml-2 text-xs font-medium tabular-nums text-hero-muted">{step.at}</span>
                  </p>
                  <p className="mt-0.5 text-[0.875rem] leading-relaxed text-hero-muted">{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby={id("facts")}>
          <h3 className="text-[0.9375rem] font-extrabold text-hero-navy" id={id("facts")}>
            What you&apos;ve told HeroOS
          </h3>
          <dl className="mt-2 divide-y divide-hero-border rounded-2xl border border-hero-border">
            {s.facts.map(([term, detail]) => (
              <div className="grid grid-cols-[8.5rem_1fr] gap-3 px-4 py-2.5 text-[0.875rem]" key={term}>
                <dt className="text-hero-muted">{term}</dt>
                <dd className="font-semibold text-hero-navy">{detail}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby={id("open")}>
          <h3 className="text-[0.9375rem] font-extrabold text-hero-navy" id={id("open")}>
            Still open
          </h3>
          <ul className="mt-2 space-y-1.5 text-[0.875rem] text-hero-navy/85">
            {s.open.map((item) => (
              <li className="flex gap-2" key={item}>
                <HelpIcon className="mt-[0.15rem] size-4 shrink-0 text-hero-muted" />
                {item}
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby={id("context")} className="border-t border-hero-border pt-4">
          <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted" id={id("context")}>
            Context HeroOS used
          </h3>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {s.context.map((item) => (
              <li className="rounded-full bg-hero-navy/[0.05] px-2.5 py-1 text-[0.8125rem] font-medium text-hero-navy/85" key={item}>
                {item}
              </li>
            ))}
          </ul>
          <p className="mt-4">
            <Pending>Inactivity / retention notice: wording and policy to confirm</Pending>
          </p>
        </section>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- case list */

export function CaseList({
  direction,
  opts,
  activeId,
  dense = false,
}: {
  direction: Direction;
  opts: LinkOpts;
  activeId: string | null;
  dense?: boolean;
}) {
  const groups = ["Today", "Earlier"] as const;
  return (
    <nav aria-label="Your cases" className="space-y-4">
      {groups.map((group) => (
        <div key={group}>
          <h3 className="px-3 text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">{group}</h3>
          <ul className="mt-1.5 space-y-0.5">
            {CASES.filter((c) => c.group === group).map((c) => {
              const state = CASE_STATE[c.id];
              return (
                <li key={c.id}>
                  <a
                    aria-current={c.id === activeId ? "page" : undefined}
                    className={`group flex flex-col rounded-xl px-3 ${dense ? "py-2" : "py-2.5"} transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-[current=page]:bg-white aria-[current=page]:shadow-[0_1px_2px_rgb(14_30_61/0.06),0_0_0_1px_rgb(14_30_61/0.08)]`}
                    href={state ? stateHref(direction, state, opts) : stateHref(direction, "history", opts)}
                  >
                    <span className={`truncate text-[0.9375rem] font-semibold ${c.status === "closed" ? "text-hero-muted" : "text-hero-navy"}`}>
                      {c.title}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-[0.8125rem] text-hero-muted">
                      <span aria-hidden="true" className={`size-1.5 rounded-full ${CASE_STATUS[c.status].dot}`} />
                      {CASE_STATUS[c.status].label}
                      <span aria-hidden="true">·</span>
                      <span className="tabular-nums">{c.when}</span>
                    </span>
                  </a>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function CaseSearch({ value }: { value?: string }) {
  return (
    <label className="flex min-h-11 items-center gap-2 rounded-xl border border-hero-border bg-white px-3 text-[0.9375rem] text-hero-navy focus-within:border-hero-blue">
      <SearchIcon className="size-4 shrink-0 text-hero-muted" />
      <span className="sr-only">Search your cases</span>
      <input
        className="min-w-0 flex-1 bg-transparent placeholder:text-hero-muted focus-visible:outline-none"
        defaultValue={value}
        placeholder="Search cases"
        type="search"
      />
    </label>
  );
}

/* ------------------------------------------------------------- account */

const INDEX = "/design-review/oct20";
const LATER = `${INDEX}#later-pages`;

/** The only other destinations: Company Blueprint (Page 2) and the company space (Page 3). Not designed yet. */
export function LaterPageLinks({ compact = false }: { compact?: boolean }) {
  return (
    <ul className="space-y-0.5">
      {[
        ["Company Blueprint", "Page 2 · not designed yet"],
        [`${COMPANY.name} space`, "Page 3 · account, plan and services"],
      ].map(([label, note]) => (
        <li key={label}>
          <a className="flex flex-col rounded-xl px-3 py-2 transition-colors duration-150 hover:bg-hero-navy/[0.05]" href={LATER}>
            <span className="text-[0.9375rem] font-semibold text-hero-navy">{label}</span>
            {compact ? null : <span className="text-[0.75rem] text-hero-muted">{note}</span>}
          </a>
        </li>
      ))}
    </ul>
  );
}

export function Initials({ className = "size-9" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-hero-navy text-[0.8125rem] font-extrabold tracking-wide text-white ${className}`}
    >
      {PERSON.initials}
    </span>
  );
}

/** Account menu: a native popover (no script), opened from the avatar. */
export function AccountButton({ withName = false, className = "" }: { withName?: boolean; className?: string }) {
  return (
    <>
      <button
        aria-label={`Account: ${PERSON.full}`}
        className={`inline-flex min-h-11 items-center gap-2 rounded-full p-1 pr-1 transition-colors duration-150 [anchor-name:--dr-account] hover:bg-hero-navy/[0.06] ${withName ? "lg:pr-3" : ""} ${className}`}
        popoverTarget="dr-account"
        type="button"
      >
        <Initials />
        {withName ? <span className="hidden text-[0.9375rem] font-semibold text-hero-navy lg:inline">{PERSON.first}</span> : null}
      </button>
      <div
        // Anchored to its button: below it, aligned to its right edge.
        className="dr-popover fixed mt-2 w-[18rem] rounded-2xl border border-hero-border bg-white p-2 text-left shadow-[0_24px_48px_-20px_rgb(14_30_61/0.45)] [position-anchor:--dr-account] [position-area:bottom_span-left]"
        id="dr-account"
        popover="auto"
      >
        <div className="flex items-center gap-3 px-3 py-2.5">
          <Initials className="size-10" />
          <div className="min-w-0">
            <p className="truncate font-bold text-hero-navy">{PERSON.full}</p>
            <p className="truncate text-[0.8125rem] text-hero-muted">{PERSON.email}</p>
            <p className="text-[0.75rem] font-semibold text-hero-muted">
              {PERSON.role} · {COMPANY.name}
            </p>
          </div>
        </div>
        <div className="my-1 h-px bg-hero-border" />
        <LaterPageLinks />
        <div className="my-1 h-px bg-hero-border" />
        <a className="flex rounded-xl px-3 py-2 text-[0.9375rem] font-semibold text-hero-navy hover:bg-hero-navy/[0.05]" href={LATER}>
          Sign out
        </a>
      </div>
    </>
  );
}

/* ------------------------------------------------------------- review bar */

/** The reviewer's controls (not part of the design): direction, state, index. `?clean=1` hides it. */
export function ReviewBar({ direction, state, opts }: { direction: Direction; state: StateKey; opts: LinkOpts }) {
  const index = STATES.findIndex((s) => s.key === state);
  const prev = STATES[(index - 1 + STATES.length) % STATES.length];
  const next = STATES[(index + 1) % STATES.length];
  const current = STATES[index];
  const pill = "inline-flex h-7 items-center rounded-full px-2.5 font-bold transition-colors duration-150";
  return (
    <nav aria-label="Design review controls" className="flex h-11 shrink-0 items-center gap-2 bg-[#0b1730] px-2 text-[0.8125rem] text-white sm:gap-3 sm:px-4">
      <a className="hidden font-extrabold text-white sm:inline" href={INDEX}>
        Round 1 archive
      </a>
      <a className="hidden text-hero-yellow underline-offset-4 hover:underline xl:inline" href={`${INDEX}/final`}>
        Superseded: see the final Page 1
      </a>
      <div className="flex items-center gap-1 rounded-full bg-white/10 p-0.5" role="group" aria-label="Direction">
        {(["a", "b"] as const).map((d) => (
          <a
            aria-current={d === direction ? "true" : undefined}
            className={`${pill} ${d === direction ? "bg-hero-yellow text-hero-navy" : "text-white/80 hover:bg-white/10"}`}
            href={stateHref(d, state, opts)}
            key={d}
            title={DIRECTION_NAMES[d].name}
          >
            {d.toUpperCase()}
            <span className="ml-1 hidden font-semibold md:inline">{DIRECTION_NAMES[d].name}</span>
          </a>
        ))}
      </div>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        <a aria-label={`Previous state: ${prev.name}`} className={`${pill} px-1.5 hover:bg-white/10`} href={stateHref(direction, prev.key, opts)}>
          <ArrowLeftIcon className="size-4" />
        </a>
        <p className="min-w-0 truncate text-center">
          <span className="font-extrabold text-hero-yellow">{current.code}</span>{" "}
          <span className="font-semibold">{current.name}</span>
          <span className="hidden text-white/55 lg:inline"> · {current.note}</span>
        </p>
        <a aria-label={`Next state: ${next.name}`} className={`${pill} px-1.5 hover:bg-white/10`} href={stateHref(direction, next.key, opts)}>
          <ArrowRightIcon className="size-4" />
        </a>
      </div>
      <a className={`${pill} hidden text-white/80 hover:bg-white/10 sm:inline-flex`} href={stateHref(direction, state, opts, { clean: true })}>
        Hide bar
      </a>
    </nav>
  );
}
