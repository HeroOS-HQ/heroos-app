import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BuildingIcon,
  CheckIcon,
  ChevronDownIcon,
  ClockIcon,
  CloseIcon,
  DocumentIcon,
  HelpIcon,
  InfoIcon,
  PeopleIcon,
  PlusIcon,
  SendIcon,
  StoreIcon,
  UserIcon,
} from "@/components/site/icons";

import {
  CASE_OPENS,
  type AdviserTurn,
  FINAL_NEXT,
  FINAL_STATES,
  type FinalState,
  type FinalTurn,
  finalTurns,
  FIRST_INQUIRY,
  STATUS,
} from "./final-scenario";
import { CandidateBrandMark, LogoSymbol } from "./brand";
import { CaseSearch, iconButton, StatusChip, TONE, ToneLabel } from "./parts";
import { CASE_STATUS, CASES, type CaseRef, COMPANY, PERSON } from "./scenario";

/**
 * Final Page 1, Ask HeroOS: one persistent workspace, consolidated from
 * Direction A ("Quiet Desk"). The empty page is the new-question experience;
 * sending turns the same surface into the case. Cases live in a drawer,
 * case status in a slide-over, and the other two pages (Company Blueprint,
 * Company Space) behind the account menu. HeroOS speaks with its own symbol.
 * There is no mascot on this page.
 */

const BASE = "/design-review/oct20";
const LATER = `${BASE}#later-pages`;

export function finalHref(state: FinalState, clean: boolean) {
  const path = state === "empty" ? `${BASE}/final` : `${BASE}/final/${state}`;
  return clean ? `${path}?clean=1` : path;
}

/* ------------------------------------------------------------- identity */

/**
 * HeroOS's mark, the adviser's identity, in the thread and above the question:
 * JJ's logo on its own (no tile), in the same boxes as before so nothing moves.
 */
function Mark({ size = "turn", breathe = false }: { size?: "turn" | "hero"; breathe?: boolean }) {
  const hero = size === "hero";
  return (
    <span
      aria-hidden="true"
      className={`relative inline-flex shrink-0 items-center justify-center ${hero ? "size-14 sm:size-16" : "size-8"} ${
        breathe ? "dr-breathe rounded-full" : ""
      }`}
    >
      {/* An invisible strut with the previous mark's height keeps the same text baseline, so nothing around the mark moves. */}
      <span className={hero ? "h-7 w-0 sm:h-8" : "h-[0.95rem] w-0"} />
      <LogoSymbol className={`absolute ${hero ? "size-12 sm:size-14" : "size-7"}`} />
    </span>
  );
}

export function Person({ className = "size-8 text-[0.6875rem]" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-hero-navy font-extrabold tracking-wide text-white ${className}`}
    >
      {PERSON.initials}
    </span>
  );
}

/**
 * The page's quiet atmosphere: two soft lights in the logo's colours (navy
 * blue and yellow, overlapping like its bubbles), dimmed once a case is open.
 */
export function Backdrop({ quiet }: { quiet: boolean }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,#fbfaf8_0%,#f4f3ef_100%)]" />
      <div className={quiet ? "opacity-40" : ""}>
        {/* Radial gradients, not blur filters: large blurs band into visible rings. */}
        <div className="absolute left-1/2 top-[40%] size-[30rem] -translate-x-[80%] -translate-y-1/2 bg-[radial-gradient(closest-side,rgb(61_107_196/0.13),rgb(61_107_196/0.05)_55%,transparent)] sm:size-[46rem]" />
        <div className="absolute left-1/2 top-[44%] size-[28rem] -translate-x-[20%] -translate-y-1/2 bg-[radial-gradient(closest-side,rgb(255_212_1/0.18),rgb(255_212_1/0.06)_55%,transparent)] sm:size-[44rem]" />
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- header */

const ghost =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full px-3 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-expanded:bg-white aria-expanded:shadow-[0_0_0_1px_rgb(14_30_61/0.1)]";

/** The workspace header, shared by every page (Pages 2 and 3 pass `menuCurrent`). */
export function Header({
  state,
  clean,
  caseRef,
  menuCurrent,
}: {
  state: FinalState;
  clean: boolean;
  caseRef: CaseRef | null;
  menuCurrent?: "blueprint" | "space";
}) {
  const href = (s: FinalState) => finalHref(s, clean);
  const casesOpen = state === "cases";
  const statusOpen = state === "status";
  return (
    <header className="relative z-20 grid h-16 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-2 sm:grid-cols-[1fr_auto_1fr] sm:px-5">
      <div className="flex items-center gap-1 sm:gap-1.5">
        <a aria-label="HeroOS: ask a new question" className="hidden min-h-11 items-center rounded-lg px-1 sm:inline-flex" href={href("empty")}>
          <CandidateBrandMark />
        </a>
        <span aria-hidden="true" className="mx-1.5 hidden h-5 w-px bg-hero-navy/15 sm:block" />
        <a aria-expanded={casesOpen} aria-label="Cases" className={ghost} href={casesOpen ? href("empty") : href("cases")}>
          <ClockIcon className="size-5" />
          <span className="hidden sm:inline">Cases</span>
        </a>
      </div>

      <div className="flex min-w-0 justify-center">
        {state === "opening" ? (
          <span className="flex min-h-11 items-center gap-2.5 px-3" role="status">
            <span className="text-[0.875rem] font-semibold text-hero-muted">Opening a case…</span>
            <span aria-hidden="true" className="dr-shimmer h-2.5 w-24 rounded-full max-sm:hidden" />
          </span>
        ) : caseRef ? (
          <a
            aria-expanded={statusOpen}
            aria-label={`${caseRef.title}. ${CASE_STATUS[caseRef.status].label}. ${statusOpen ? "Close" : "Open"} case status`}
            className="group inline-flex min-h-10 min-w-0 max-w-full items-center gap-2 rounded-full border border-hero-border bg-white/70 px-3.5 shadow-[0_1px_2px_rgb(14_30_61/0.04)] backdrop-blur transition-colors duration-150 hover:bg-white aria-expanded:border-hero-blue/50 aria-expanded:bg-white sm:max-w-[34rem]"
            href={statusOpen ? href("warning") : href("status")}
          >
            <span className={`truncate text-[0.9375rem] font-extrabold text-hero-navy ${state === "conversation" ? "dr-title-in" : ""}`}>
              {caseRef.title}
            </span>
            <span aria-hidden="true" className={`size-2 shrink-0 rounded-full max-sm:hidden ${CASE_STATUS[caseRef.status].dot}`} />
            <span className="hidden shrink-0 text-[0.8125rem] font-semibold text-hero-muted md:inline">{CASE_STATUS[caseRef.status].label}</span>
            <ChevronDownIcon className="size-4 shrink-0 text-hero-muted transition-transform duration-200 group-aria-expanded:rotate-180" />
          </a>
        ) : (
          <a aria-label="HeroOS" className="inline-flex min-h-11 items-center sm:hidden" href={href("empty")}>
            <CandidateBrandMark />
          </a>
        )}
      </div>

      <div className="flex items-center justify-end gap-1">
        {caseRef ? (
          <a aria-label="New question" className={`${iconButton} max-sm:hidden`} href={href("empty")} title="New question">
            <PlusIcon className="size-5" />
          </a>
        ) : null}
        <AccountMenu current={menuCurrent} />
      </div>
    </header>
  );
}

/** The only way to the other two pages and the account: a small menu, never permanent navigation. */
function AccountMenu({ current }: { current?: "blueprint" | "space" }) {
  const items = [
    {
      key: "blueprint",
      label: "Company Blueprint",
      note: "Company details, jurisdiction and policies",
      icon: <BuildingIcon className="size-5" />,
      href: `${BASE}/blueprint`,
    },
    {
      key: "space",
      label: "Company Space",
      note: "Your access and company overview",
      icon: <StoreIcon className="size-5" />,
      href: `${BASE}/space`,
    },
  ];
  const utility = "flex min-h-10 items-center gap-3 rounded-xl px-3 text-[0.875rem] font-semibold text-hero-navy/80 transition-colors duration-150 hover:bg-hero-navy/[0.04] hover:text-hero-navy";
  return (
    <>
      <button
        aria-label={`Menu: ${PERSON.full}, ${COMPANY.name}`}
        className="inline-flex min-h-11 items-center gap-1 rounded-full p-1 transition-colors duration-150 [anchor-name:--final-account] hover:bg-hero-navy/[0.05] sm:pr-2"
        popoverTarget="final-account"
        type="button"
      >
        <Person className="size-9 text-[0.75rem]" />
        <ChevronDownIcon className="size-4 text-hero-muted max-sm:hidden" />
      </button>
      <div
        // Anchored to its button: below it, aligned to its right edge.
        className="dr-popover fixed mt-2 w-[19rem] rounded-2xl border border-hero-border bg-white p-2 text-left shadow-[0_24px_48px_-20px_rgb(14_30_61/0.45)] [position-anchor:--final-account] [position-area:bottom_span-left]"
        id="final-account"
        popover="auto"
      >
        <div className="flex items-center gap-3 px-3 py-2.5">
          <Person className="size-10 text-[0.8125rem]" />
          <div className="min-w-0">
            <p className="truncate font-bold text-hero-navy">{PERSON.full}</p>
            <p className="truncate text-[0.8125rem] text-hero-muted">{COMPANY.legalName}</p>
          </div>
        </div>
        <div className="my-1 h-px bg-hero-border" />
        <ul>
          {items.map((item) => (
            <li key={item.label}>
              <a
                aria-current={item.key === current ? "page" : undefined}
                className="flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors duration-150 hover:bg-hero-navy/[0.04] aria-[current=page]:bg-hero-blue-tint/70"
                href={item.href}
              >
                <span className="mt-0.5 text-hero-muted">{item.icon}</span>
                <span className="min-w-0">
                  <span className="block text-[0.9375rem] font-semibold text-hero-navy">{item.label}</span>
                  <span className="block text-[0.8125rem] text-hero-muted">{item.note}</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
        {/* Utilities, not product pages: the account is a menu surface, never a fourth page. */}
        <div className="my-1 h-px bg-hero-border" />
        <ul aria-label="Account">
          <li>
            <a className={utility} href={LATER}>
              <UserIcon className="size-4 text-hero-muted" />
              Account settings
            </a>
          </li>
          <li>
            <a className={utility} href={LATER}>
              <span aria-hidden="true" className="size-4" />
              Sign out
            </a>
          </li>
        </ul>
      </div>
    </>
  );
}

/* ------------------------------------------------------------- composer */

function Composer({
  variant,
  action,
  clean,
  value,
  disabled = false,
}: {
  variant: "ask" | "reply";
  action: string;
  clean: boolean;
  value?: string;
  disabled?: boolean;
}) {
  const ask = variant === "ask";
  const id = ask ? "ask-heroos" : "reply-heroos";
  return (
    <form action={action.split("?")[0]} method="get">
      {clean ? <input name="clean" type="hidden" value="1" /> : null}
      <div
        className={`dr-composer rounded-[1.75rem] border border-hero-navy/[0.12] bg-white transition-[border-color,box-shadow] duration-200 focus-within:border-hero-blue/70 ${
          ask
            ? "shadow-[0_1px_2px_rgb(14_30_61/0.05),0_28px_60px_-30px_rgb(14_30_61/0.45)] focus-within:shadow-[0_0_0_4px_rgb(61_107_196/0.12),0_28px_60px_-30px_rgb(14_30_61/0.45)]"
            : "shadow-[0_1px_2px_rgb(14_30_61/0.05),0_16px_36px_-24px_rgb(14_30_61/0.4)] focus-within:shadow-[0_0_0_4px_rgb(61_107_196/0.12),0_16px_36px_-24px_rgb(14_30_61/0.4)]"
        } ${disabled ? "opacity-70" : ""}`}
      >
        <label className="sr-only" htmlFor={id}>
          {ask ? "Explain the situation in your own words" : "Reply to HeroOS"}
        </label>
        <textarea
          className={`block w-full resize-none bg-transparent px-6 text-hero-navy placeholder:text-hero-muted/80 focus-visible:outline-none ${
            ask ? "min-h-[7rem] pt-5 text-[1.0625rem] leading-relaxed sm:min-h-[7.75rem] sm:text-lg" : "min-h-[3.25rem] pt-4 text-base leading-relaxed"
          }`}
          defaultValue={value}
          disabled={disabled}
          id={id}
          placeholder={
            disabled
              ? "HeroOS is reviewing what you've described…"
              : ask
                ? "For example: one of my team hasn't come in for two days and isn't answering."
                : "Reply to HeroOS…"
          }
          rows={ask ? 3 : 1}
        />
        <div className="flex items-center gap-2 px-3 pb-3">
          {ask ? null : (
            <button
              className="inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:bg-hero-navy/[0.05] hover:text-hero-navy disabled:cursor-not-allowed"
              disabled={disabled}
              type="button"
            >
              <DocumentIcon className="size-[1.125rem]" />
              <span className="max-sm:sr-only">Add a document</span>
            </button>
          )}
          <button
            aria-label="Send"
            className={`dr-send ml-auto inline-flex shrink-0 items-center justify-center rounded-full bg-hero-navy text-white shadow-[0_10px_20px_-10px_rgb(14_30_61/0.9)] transition-[background-color,transform] duration-150 hover:-translate-y-px hover:bg-[#182c55] ${
              ask ? "size-12" : "size-11"
            }`}
            disabled={disabled}
            type="submit"
          >
            <SendIcon className="size-5" />
          </button>
        </div>
      </div>
    </form>
  );
}

/* ----------------------------------------------------------------- thread */

function YouTurn({ text, at }: { text: string; at: string }) {
  return (
    <article aria-label={`${PERSON.first}, ${at}`}>
      <header className="flex items-center gap-3">
        <Person />
        <p className="flex items-baseline gap-2 text-[0.875rem]">
          <span className="font-bold text-hero-navy">{PERSON.first}</span>
          <time className="text-xs tabular-nums text-hero-muted">{at}</time>
        </p>
      </header>
      <p className="mt-2 rounded-2xl border border-hero-navy/[0.08] bg-white px-4 py-3 text-base leading-[1.65] text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] sm:ml-11">
        {text}
      </p>
    </article>
  );
}

const boxHeading = "text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)";

function Numbered({ items }: { items: string[] }) {
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

function AdviserTurnView({ turn, latest, nextHref }: { turn: AdviserTurn; latest: boolean; nextHref: string }) {
  const id = `turn-${turn.id}`;
  const guidance = turn.tone === "guidance";
  return (
    <article aria-labelledby={id} className={`tone-${turn.tone}`}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Mark />
        <h3 className="text-[0.875rem] font-extrabold text-hero-navy" id={id}>
          HeroOS<span className="sr-only">, {TONE[turn.tone].label}</span>
        </h3>
        <ToneLabel tone={turn.tone} />
        <time className="ml-auto text-xs tabular-nums text-hero-muted">{turn.at}</time>
      </header>

      <div
        className={
          guidance
            ? "mt-2 space-y-3 border-l-2 border-(--tone-rule) pl-4 text-base leading-[1.65] text-hero-navy sm:ml-[0.9375rem] sm:pl-[1.6875rem]"
            : "relative mt-2.5 space-y-3 overflow-hidden rounded-2xl border border-(--tone-line) bg-(--tone-bg) py-4 pl-5 pr-4 text-base leading-[1.65] text-hero-navy shadow-[0_14px_34px_-26px_rgb(14_30_61/0.5)] sm:ml-11 sm:py-5 sm:pr-5"
        }
      >
        {guidance ? null : <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-(--tone-rail)" />}
        {turn.lead ? <p>{turn.lead}</p> : null}
        {turn.title ? <p className="text-[1.1875rem] font-extrabold leading-snug tracking-[-0.01em] text-(--tone-ink)">{turn.title}</p> : null}
        {turn.body?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}

        {turn.steps ? (
          <div className="rounded-xl bg-white/90 px-4 py-3 ring-1 ring-(--tone-line)">
            <p className={boxHeading}>{turn.steps.heading}</p>
            {turn.steps.items.length > 1 ? (
              <Numbered items={turn.steps.items} />
            ) : (
              <p className="mt-1.5 flex gap-2">
                <ArrowRightIcon className="mt-[0.3rem] size-4 shrink-0 text-(--tone-rail)" />
                {turn.steps.items[0]}
              </p>
            )}
          </div>
        ) : null}

        {turn.next || turn.provide ? (
          <div className="grid gap-3 md:grid-cols-[1.4fr_1fr]">
            {turn.next ? (
              <div className="rounded-xl bg-white/90 px-4 py-3 ring-1 ring-(--tone-line)">
                <p className={boxHeading}>{turn.next.heading}</p>
                <Numbered items={turn.next.items} />
              </div>
            ) : null}
            {turn.provide ? (
              <div className="rounded-xl bg-white/90 px-4 py-3 ring-1 ring-(--tone-line)">
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

        {turn.question ? (
          <div className="rounded-xl bg-white px-4 py-3.5 ring-1 ring-(--tone-line)">
            <p className="flex items-center gap-1.5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">
              <HelpIcon className="size-3.5" />
              HeroOS needs to know
            </p>
            <p className="mt-1 font-semibold leading-snug">{turn.question}</p>
            {latest && turn.chips ? (
              <ul aria-label="Quick replies" className="mt-3 flex flex-wrap gap-2">
                {turn.chips.map((chip) => (
                  <li key={chip}>
                    <a
                      className="inline-flex min-h-10 items-center rounded-full border border-(--tone-line) bg-white px-4 text-[0.875rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-(--tone-chip)"
                      href={nextHref}
                    >
                      {chip}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
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
                      ? "inline-flex min-h-11 items-center gap-2 rounded-full bg-(--tone-rail) px-5 text-[0.9375rem] font-bold text-white shadow-[0_10px_20px_-12px_rgb(169_47_108/0.9)] transition-transform duration-150 hover:-translate-y-px"
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
            {turn.note ? (
              <p className="mt-2.5 flex items-center gap-1.5 text-[0.8125rem] text-hero-navy/75">
                <InfoIcon className="size-4 shrink-0 text-(--tone-rail)" />
                {turn.note}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

/** Between Send and the first answer: HeroOS is working; no visible reasoning. */
function OpeningTurn() {
  return (
    <article aria-label="HeroOS is reviewing what you've described" role="status">
      <header className="flex items-center gap-3">
        <Mark breathe />
        <p className="text-[0.875rem]">
          <span className="font-extrabold text-hero-navy">HeroOS</span>{" "}
          <span className="font-medium text-hero-muted">is reviewing what you&apos;ve described</span>
          <span aria-hidden="true" className="ml-2 inline-flex gap-1 align-middle">
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
            <span className="dr-dot size-1.5 rounded-full bg-hero-blue" />
          </span>
        </p>
      </header>
      <div aria-hidden="true" className="mt-3 space-y-2.5 border-l-2 border-[#d9e3f6] pl-4 sm:ml-[0.9375rem] sm:pl-[1.6875rem]">
        <span className="dr-shimmer block h-3 w-[85%] rounded-full" />
        <span className="dr-shimmer block h-3 w-[60%] rounded-full" />
      </div>
    </article>
  );
}

function Thread({ turns, caseRef, opening, nextHref }: { turns: FinalTurn[]; caseRef: CaseRef; opening: boolean; nextHref: string }) {
  const lastAdviser = [...turns].reverse().find((turn) => turn.kind === "heroos");
  return (
    <ol aria-label={`Conversation: ${caseRef.title}`} className="flex flex-col gap-7" role="log">
      {turns.map((turn, index) => (
        <li className={index === turns.length - 1 && !opening ? "dr-rise" : ""} key={turn.id}>
          {turn.kind === "you" ? (
            <YouTurn at={turn.at} text={turn.text} />
          ) : turn.kind === "heroos" ? (
            <AdviserTurnView latest={turn === lastAdviser} nextHref={nextHref} turn={turn} />
          ) : turn.kind === "event" ? (
            <p className="flex items-center gap-3 text-[0.8125rem] text-hero-muted sm:pl-11" role="note">
              <CheckIcon className="size-4 shrink-0 text-hero-blue" />
              <span>
                {turn.text}: <span className="font-bold text-hero-navy">{caseRef.title}</span>
              </span>
              <span aria-hidden="true" className="h-px flex-1 bg-hero-border" />
            </p>
          ) : turn.kind === "resume" ? (
            <div className="flex items-center gap-3" role="separator">
              <span className="h-px flex-1 bg-hero-blue/25" />
              <span className="text-[0.8125rem] font-bold text-hero-blue-ink">{turn.text}</span>
              <span className="h-px flex-1 bg-hero-blue/25" />
            </div>
          ) : (
            <p className="text-center">
              <a className="inline-flex min-h-9 items-center rounded-full bg-hero-navy/[0.05] px-3.5 text-[0.8125rem] font-semibold text-hero-muted hover:bg-hero-navy/[0.08]" href={nextHref}>
                {turn.text}
              </a>
            </p>
          )}
        </li>
      ))}
      {opening ? (
        <li className="dr-rise-late">
          <OpeningTurn />
        </li>
      ) : null}
    </ol>
  );
}

/* ------------------------------------------------------------ drawers */

function CasesDrawer({ clean }: { clean: boolean }) {
  const close = finalHref("empty", clean);
  const groups = ["Today", "Earlier"] as const;
  return (
    <div className="absolute inset-0 z-40">
      <a aria-label="Close cases" className="dr-fade absolute inset-0 bg-hero-navy/20" href={close} />
      <aside
        aria-labelledby="cases-title"
        className="dr-from-left absolute inset-y-0 left-0 flex w-[min(21rem,88vw)] flex-col border-r border-hero-border bg-[#fbfaf8] shadow-[24px_0_60px_-28px_rgb(14_30_61/0.45)]"
      >
        <div className="flex h-16 shrink-0 items-center justify-between pl-5 pr-2">
          <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="cases-title">
            Cases
          </h2>
          <a aria-label="Close cases" className={iconButton} href={close}>
            <CloseIcon className="size-5" />
          </a>
        </div>
        <div className="space-y-2.5 px-3">
          <a
            className="flex min-h-11 items-center gap-2 rounded-xl border border-hero-border bg-white px-3.5 text-[0.9375rem] font-semibold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.04)] transition-colors duration-150 hover:bg-hero-blue-tint"
            href={close}
          >
            <PlusIcon className="size-5" />
            New question
          </a>
          <CaseSearch />
        </div>
        <nav aria-label="Your cases" className="mt-5 min-h-0 flex-1 space-y-5 overflow-y-auto px-1 pb-5">
          {groups.map((group) => (
            <div key={group}>
              <h3 className="px-4 text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">{group}</h3>
              <ul className="mt-1.5 space-y-0.5 px-1">
                {CASES.filter((c) => c.group === group).map((c) => {
                  const opens = CASE_OPENS[c.id];
                  return (
                    <li key={c.id}>
                      <a
                        className="flex flex-col rounded-xl px-3 py-2.5 transition-colors duration-150 hover:bg-hero-navy/[0.05]"
                        href={opens ? finalHref(opens, clean) : finalHref("cases", clean)}
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
      </aside>
    </div>
  );
}

const sectionTitle = "text-[0.9375rem] font-extrabold text-hero-navy";

function StatusPanel({ caseRef, clean }: { caseRef: CaseRef; clean: boolean }) {
  const close = finalHref("warning", clean);
  const marker: Record<string, string> = {
    done: "bg-hero-navy text-white",
    guidance: "tone-guidance bg-(--tone-chip) text-(--tone-ink)",
    warning: "tone-warning bg-(--tone-chip) text-(--tone-ink)",
    current: "dr-ring bg-white ring-2 ring-hero-blue",
  };
  return (
    <div className="absolute inset-0 z-40">
      <a aria-label="Close case status" className="dr-fade absolute inset-0 bg-hero-navy/20" href={close} />
      <aside
        aria-labelledby="status-title"
        className="dr-panel-in absolute inset-x-0 bottom-0 max-h-[88%] overflow-y-auto rounded-t-[1.75rem] bg-white shadow-[0_-20px_60px_-24px_rgb(14_30_61/0.45)] sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[27rem] sm:rounded-none sm:rounded-l-[1.75rem]"
      >
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-hero-border bg-white/95 px-6 pb-4 pt-5 backdrop-blur">
          <div className="min-w-0 flex-1">
            <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Case status</p>
            <h2 className="mt-1 text-[1.25rem] font-extrabold leading-tight tracking-[-0.015em] text-hero-navy" id="status-title">
              {caseRef.title}
            </h2>
            <p className="mt-1 text-[0.8125rem] text-hero-muted">Named by HeroOS · Opened today, 09:12</p>
          </div>
          <a aria-label="Close case status" className={`${iconButton} -mr-2 -mt-1`} href={close}>
            <CloseIcon className="size-5" />
          </a>
        </div>

        <div className="space-y-6 px-6 py-5">
          <section aria-labelledby="st-now">
            <div className="flex flex-wrap items-center gap-2">
              <StatusChip status={caseRef.status} />
              <p className="text-[0.875rem] text-hero-muted">
                <span className="font-semibold text-hero-navy" id="st-now">
                  Now:
                </span>{" "}
                {STATUS.now}
              </p>
            </div>
            <p className="mt-2.5 text-[0.9375rem] leading-relaxed text-hero-navy/85">{STATUS.summary}</p>
          </section>

          <section aria-labelledby="st-next" className="tone-guidance rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5">
            <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)" id="st-next">
              Your next step
            </h3>
            <p className="mt-1 text-[0.9375rem] font-semibold leading-snug text-hero-navy">{STATUS.nextStep}</p>
          </section>

          <div className="grid gap-5">
            <section aria-labelledby="st-done">
              <h3 className={sectionTitle} id="st-done">
                Done so far
              </h3>
              <ul className="mt-2 space-y-1.5 text-[0.875rem] text-hero-navy/85">
                {STATUS.done.map((item) => (
                  <li className="flex gap-2" key={item}>
                    <CheckIcon className="mt-[0.15rem] size-4 shrink-0 text-hero-success" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="st-needed">
              <h3 className={sectionTitle} id="st-needed">
                Still needed
              </h3>
              <ul className="mt-2 space-y-1.5 text-[0.875rem] text-hero-navy/85">
                {STATUS.needed.map((item) => (
                  <li className="flex gap-2" key={item}>
                    <span aria-hidden="true" className="mt-[0.3rem] size-3 shrink-0 rounded-full border-2 border-hero-control" />
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section aria-labelledby="st-facts">
            <h3 className={sectionTitle} id="st-facts">
              What you&apos;ve told HeroOS
            </h3>
            <dl className="mt-2 divide-y divide-hero-border rounded-2xl border border-hero-border">
              {STATUS.facts.map(([term, detail]) => (
                <div className="grid grid-cols-[8rem_1fr] gap-3 px-4 py-2.5 text-[0.875rem]" key={term}>
                  <dt className="text-hero-muted">{term}</dt>
                  <dd className="font-semibold text-hero-navy">{detail}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section aria-labelledby="st-history">
            <h3 className={sectionTitle} id="st-history">
              Case history
            </h3>
            <ol className="relative mt-3 space-y-3 before:absolute before:bottom-2 before:left-[0.5625rem] before:top-2 before:w-px before:bg-hero-border">
              {STATUS.history.map((step) => (
                <li className="relative flex items-start gap-3" key={step.text}>
                  <span aria-hidden="true" className={`relative z-10 mt-0.5 inline-flex size-[1.125rem] shrink-0 items-center justify-center rounded-full ${marker[step.tone]}`}>
                    {step.tone === "done" ? <CheckIcon className="size-2.5" /> : null}
                    {step.tone === "current" ? <span className="size-1.5 rounded-full bg-hero-blue" /> : null}
                  </span>
                  <p className={`text-[0.875rem] leading-snug ${step.tone === "current" ? "font-extrabold text-hero-blue-ink" : "font-semibold text-hero-navy"}`}>
                    {step.text}
                    <span className="ml-2 text-xs font-medium tabular-nums text-hero-muted">{step.at}</span>
                  </p>
                </li>
              ))}
            </ol>
          </section>

          {/* Context transparency lives here, folded away, never under the question. */}
          <details className="group rounded-2xl border border-hero-border px-4 py-3">
            <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between text-[0.875rem] font-semibold text-hero-navy [&::-webkit-details-marker]:hidden">
              How HeroOS tailored this case
              <ChevronDownIcon className="size-4 text-hero-muted transition-transform duration-200 group-open:rotate-180" />
            </summary>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {STATUS.context.map((item) => (
                <li className="rounded-full bg-hero-navy/[0.05] px-2.5 py-1 text-[0.8125rem] font-medium text-hero-navy/85" key={item}>
                  {item}
                </li>
              ))}
            </ul>
          </details>
        </div>
      </aside>
    </div>
  );
}

/* -------------------------------------------------------------- the page */

export function FinalWorkspace({ state, clean }: { state: FinalState; clean: boolean }) {
  const { caseRef, turns } = finalTurns(state);
  const statusCase = state === "status" ? CASES.find((c) => c.id === "attendance")! : null;
  const opening = state === "opening";
  const next = finalHref(FINAL_NEXT[state], clean);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <Backdrop quiet={caseRef !== null} />
      <Header caseRef={caseRef} clean={clean} state={state} />

      <main className="relative z-10 flex min-h-0 flex-1 flex-col" id="main">
        {caseRef ? (
          <>
            <div className="dr-log min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto mb-auto w-full max-w-[46rem] px-4 pb-8 pt-3 sm:px-6 sm:pt-7">
                <h1 className="sr-only">{opening ? "Opening your case" : caseRef.title}</h1>
                <Thread caseRef={caseRef} nextHref={next} opening={opening} turns={turns} />
              </div>
            </div>
            <div className="shrink-0 px-3 pb-3 sm:px-6 sm:pb-6">
              <div className="mx-auto max-w-[46rem]">
                <Composer action={next} clean={clean} disabled={opening} variant="reply" />
              </div>
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col px-4 pb-4 sm:items-center sm:justify-center sm:px-6 sm:pb-[12vh]">
            <div className="flex flex-1 flex-col items-center justify-center text-center sm:flex-none">
              <span className="dr-rise">
                <Mark size="hero" />
              </span>
              <p className="dr-rise mt-6 text-[0.9375rem] font-semibold text-hero-muted sm:text-base">
                {state === "cases" ? `Welcome back, ${PERSON.first}.` : `Welcome, ${PERSON.first}.`}
              </p>
              <h1 className="dr-rise mt-2 text-[2.375rem] font-extrabold leading-[1.04] tracking-[-0.04em] text-hero-navy sm:text-[3.5rem]">
                What can HR do for you today?
              </h1>
              <p className="dr-rise-late mt-4 text-[1.0625rem] text-hero-muted sm:text-xl">Explain the situation in your own words.</p>
            </div>
            <div className="w-full sm:mt-11 sm:max-w-[46rem]">
              <Composer
                action={finalHref("opening", clean)}
                clean={clean}
                value={state === "typing" ? FIRST_INQUIRY : undefined}
                variant="ask"
              />
            </div>
          </div>
        )}
      </main>

      {state === "cases" ? <CasesDrawer clean={clean} /> : null}
      {statusCase ? <StatusPanel caseRef={statusCase} clean={clean} /> : null}
    </div>
  );
}

/** The reviewer's controls (not part of the design). `?clean=1` hides them. */
export function FinalReviewBar({ state, clean }: { state: FinalState; clean: boolean }) {
  const index = FINAL_STATES.findIndex((s) => s.key === state);
  const prev = FINAL_STATES[(index - 1 + FINAL_STATES.length) % FINAL_STATES.length];
  const next = FINAL_STATES[(index + 1) % FINAL_STATES.length];
  const current = FINAL_STATES[index];
  const pill = "inline-flex h-7 items-center rounded-full px-2.5 font-bold transition-colors duration-150 hover:bg-white/10";
  return (
    <nav aria-label="Design review controls" className="flex h-11 shrink-0 items-center gap-2 bg-[#0b1730] px-2 text-[0.8125rem] text-white sm:gap-3 sm:px-4">
      <a className="font-extrabold text-white" href={BASE}>
        Page 1 · Final
      </a>
      <span className="hidden text-white/55 lg:inline">Ask HeroOS · mockup, not connected to data</span>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        <a aria-label={`Previous state: ${prev.name}`} className={`${pill} px-1.5`} href={finalHref(prev.key, clean)}>
          <ArrowLeftIcon className="size-4" />
        </a>
        <p className="min-w-0 truncate">
          <span className="font-extrabold text-hero-yellow">{current.n}</span> <span className="font-semibold">{current.name}</span>
          <span className="hidden text-white/55 md:inline"> · {current.note}</span>
        </p>
        <a aria-label={`Next state: ${next.name}`} className={`${pill} px-1.5`} href={finalHref(next.key, clean)}>
          <ArrowRightIcon className="size-4" />
        </a>
      </div>
      <a className={`${pill} hidden text-white/80 sm:inline-flex`} href={finalHref(state, true)}>
        Hide bar
      </a>
    </nav>
  );
}

export function FinalScreen({ state, clean }: { state: FinalState; clean: boolean }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {clean ? null : <FinalReviewBar clean={clean} state={state} />}
      <FinalWorkspace clean={clean} state={state} />
    </div>
  );
}
