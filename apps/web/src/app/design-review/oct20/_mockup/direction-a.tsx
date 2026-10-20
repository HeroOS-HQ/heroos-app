import { BrandMark } from "@/components/site/brand-mark";
import { ChevronDownIcon, ClockIcon, CloseIcon, PlusIcon } from "@/components/site/icons";

import {
  AccountButton,
  CaseList,
  CaseSearch,
  CaseStatusBody,
  Composer,
  ConversationLog,
  hiddenFields,
  iconButton,
  Initials,
  LaterPageLinks,
  type LinkOpts,
  NEXT,
  Skyline,
  stateHref,
  TrustLine,
} from "./parts";
import { CASE_STATUS, CASES, COMPANY, FIRST_QUESTION, PERSON, type StateKey, turnsFor } from "./scenario";

/**
 * Direction A, "Quiet Desk" (focused advisory). One question on an almost
 * empty desk. There is no visible navigation: a single "Cases" button opens a
 * drawer that holds the case history and the two other pages; the case title
 * sits in the top bar and opens the case status as a slide-over.
 */
export function DirectionA({ state, opts }: { state: StateKey; opts: LinkOpts }) {
  const href = (s: StateKey) => stateHref("a", s, opts);
  const { caseId, turns } = turnsFor(state);
  const caseRef = CASES.find((c) => c.id === caseId) ?? null;
  const inCase = caseRef !== null;
  const opening = state === "understanding";
  const caseBase: StateKey = state === "status" ? "warning" : state;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[#f6f5f2]">
      {/* A faint light from above: the desk, not a dashboard. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[26rem] bg-[radial-gradient(55%_100%_at_50%_0%,rgb(88_136_232/0.11),transparent)]"
      />

      <header className="relative z-20 grid h-16 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 px-2 sm:px-4">
        <div className="flex items-center gap-1">
          <a aria-label="Cases and menu" className={iconButton} href={href("history")}>
            <ClockIcon className="size-[1.375rem]" />
            <span className="hidden sm:inline">Cases</span>
          </a>
          <a aria-label="HeroOS: ask a new question" className="hidden min-h-11 items-center rounded-lg px-1.5 sm:inline-flex" href={href("empty")}>
            <BrandMark />
          </a>
        </div>

        <div className="flex min-w-0 justify-center">
          {inCase ? (
            opening ? (
              <span className="flex min-h-11 items-center gap-2.5 px-3">
                <span className="text-[0.875rem] font-semibold text-hero-muted">Opening a case…</span>
                <span aria-hidden="true" className="dr-shimmer h-3 w-28 rounded-full max-sm:hidden" />
              </span>
            ) : (
              <a
                aria-label={`${caseRef.title}. ${CASE_STATUS[caseRef.status].label}. Open case status`}
                aria-expanded={state === "status"}
                className="group inline-flex min-h-11 min-w-0 max-w-full items-center gap-2 rounded-full px-3.5 transition-colors duration-150 hover:bg-white hover:shadow-[0_0_0_1px_rgb(14_30_61/0.08)] aria-expanded:bg-white aria-expanded:shadow-[0_0_0_1px_rgb(14_30_61/0.1)]"
                href={state === "status" ? href(caseBase) : href("status")}
              >
                <span className={`truncate text-[0.9375rem] font-extrabold text-hero-navy ${state === "conversation" ? "dr-title-in" : ""}`}>
                  {caseRef.title}
                </span>
                <span aria-hidden="true" className={`size-2 shrink-0 rounded-full max-sm:hidden ${CASE_STATUS[caseRef.status].dot}`} />
                <span className="hidden shrink-0 text-[0.8125rem] font-semibold text-hero-muted md:inline">
                  {CASE_STATUS[caseRef.status].label}
                </span>
                <ChevronDownIcon className="size-4 shrink-0 text-hero-muted transition-transform duration-200 group-aria-expanded:rotate-180" />
              </a>
            )
          ) : (
            <a aria-label="HeroOS" className="inline-flex min-h-11 items-center sm:hidden" href={href("empty")}>
              <BrandMark />
            </a>
          )}
        </div>

        <div className="flex items-center justify-end gap-1">
          {inCase ? (
            <a aria-label="New question" className={`${iconButton} sm:border sm:border-hero-border sm:bg-white sm:px-3.5`} href={href("empty")}>
              <PlusIcon className="size-5" />
              <span className="hidden md:inline">New question</span>
            </a>
          ) : null}
          <AccountButton className={inCase ? "max-sm:hidden" : ""} />
        </div>
      </header>

      <main className="relative z-10 flex min-h-0 flex-1 flex-col" id="main">
        {inCase ? (
          <>
            <div className="dr-log min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto mb-auto w-full max-w-[46rem] px-3 pb-6 pt-3 sm:px-6 sm:pt-6">
                <h1 className="sr-only">{opening ? "Opening your case" : caseRef.title}</h1>
                <ConversationLog
                  label={`Conversation: ${caseRef.title}`}
                  nextHref={href(NEXT[state])}
                  thinking={opening}
                  turns={turns}
                />
              </div>
            </div>
            <div className="shrink-0 px-3 pb-3 sm:px-6 sm:pb-5">
              <div className="mx-auto max-w-[46rem]">
                <Composer action={href(NEXT[state])} disabled={opening} hidden={hiddenFields(opts)} variant="reply" />
                <p className="mt-2 text-center text-[0.75rem] text-hero-muted">
                  HeroOS advises. Decisions about your people stay with you.
                </p>
              </div>
            </div>
          </>
        ) : (
          <AskDesk opts={opts} state={state} />
        )}
      </main>

      {state === "history" ? <CasesDrawer opts={opts} /> : null}
      {state === "status" && caseRef ? (
        <div className="absolute inset-0 z-40">
          <a aria-label="Close case status" className="dr-fade absolute inset-0 bg-hero-navy/25" href={href(caseBase)} />
          <aside
            aria-labelledby="cs-title"
            className="dr-panel-in absolute inset-x-0 bottom-0 max-h-[88%] overflow-y-auto rounded-t-[1.75rem] bg-white shadow-[0_-20px_60px_-20px_rgb(14_30_61/0.45)] sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[27rem] sm:rounded-none sm:rounded-l-[1.75rem]"
          >
            <CaseStatusBody caseRef={caseRef} closeHref={href(caseBase)} />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

/** The Ask page itself: a greeting, one question, one box. */
function AskDesk({ state, opts }: { state: StateKey; opts: LinkOpts }) {
  const returning = state === "history";
  const probation = CASES.find((c) => c.id === "probation")!;
  return (
    <div className="relative flex flex-1 flex-col px-4 sm:items-center sm:justify-center sm:px-6 sm:pb-24">
      <div className="flex flex-1 flex-col justify-center sm:w-full sm:max-w-[44rem] sm:flex-none">
        <p className="dr-rise text-center text-[0.9375rem] font-semibold text-hero-muted">
          {returning ? `Welcome back, ${PERSON.first}.` : `Welcome, ${PERSON.first}.`}
        </p>
        <h1 className="dr-rise mt-2 text-center text-[2.125rem] font-extrabold leading-[1.08] tracking-[-0.035em] text-hero-navy sm:text-[3rem]">
          What can HR do for you today?
        </h1>
        <p className="dr-rise-late mx-auto mt-3 max-w-[32rem] text-center text-base leading-relaxed text-hero-muted sm:text-lg">
          Explain the situation in your own words. HeroOS works out the HR side and asks only what it needs.
        </p>
      </div>

      <div className="pb-4 sm:mt-12 sm:w-full sm:max-w-[44rem] sm:pb-0">
        <div className="relative">
          <div className="relative z-10">
            <Composer
              action={stateHref("a", "understanding", opts)}
              hidden={hiddenFields(opts)}
              value={state === "typing" ? FIRST_QUESTION : undefined}
              variant="ask"
            />
          </div>
        </div>
        <TrustLine className="mt-3" />
        {returning ? (
          <p className="mt-5 text-center text-[0.875rem] text-hero-muted">
            Pick up where you left off:{" "}
            <a className="font-bold text-hero-blue-ink underline-offset-4 hover:underline" href={stateHref("a", "reopened", opts)}>
              {probation.title}
            </a>
          </p>
        ) : null}
      </div>

      <Skyline className="absolute inset-x-0 bottom-0 -z-10 hidden h-24 sm:block" />
    </div>
  );
}

/** Everything that isn't the question: case history, the two other pages, the account. */
function CasesDrawer({ opts }: { opts: LinkOpts }) {
  const close = stateHref("a", "empty", opts);
  return (
    <div className="absolute inset-0 z-40">
      <a aria-label="Close" className="dr-fade absolute inset-0 bg-hero-navy/25" href={close} />
      <aside
        aria-label="Cases and menu"
        className="dr-from-left absolute inset-y-0 left-0 flex w-[min(20.5rem,88vw)] flex-col bg-[#fbfaf8] shadow-[20px_0_60px_-20px_rgb(14_30_61/0.4)]"
      >
        <div className="flex h-16 shrink-0 items-center justify-between px-4">
          <BrandMark />
          <a aria-label="Close" className={iconButton} href={close}>
            <CloseIcon className="size-5" />
          </a>
        </div>
        <div className="space-y-3 px-3">
          <a
            className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-hero-navy px-4 text-[0.9375rem] font-bold text-white transition-colors duration-150 hover:bg-[#182c55]"
            href={close}
          >
            <PlusIcon className="size-5" />
            New question
          </a>
          <CaseSearch />
        </div>
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-1 pb-4">
          <CaseList activeId={null} direction="a" opts={opts} />
        </div>
        <div className="shrink-0 border-t border-hero-border px-1 py-2">
          <LaterPageLinks />
          <div className="mt-1 flex items-center gap-3 rounded-xl px-3 py-2">
            <Initials />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[0.9375rem] font-bold text-hero-navy">{PERSON.full}</p>
              <p className="truncate text-[0.75rem] text-hero-muted">
                {PERSON.role} · {COMPANY.name}
              </p>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
