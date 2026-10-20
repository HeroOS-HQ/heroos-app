import { BrandMark } from "@/components/site/brand-mark";
import {
  ArrowLeftIcon,
  ChecklistIcon,
  ChevronRightIcon,
  CloseIcon,
  MenuIcon,
  PlusIcon,
} from "@/components/site/icons";

import {
  AccountButton,
  CaseList,
  CaseSearch,
  CaseStatusBody,
  Composer,
  ConversationLog,
  hiddenFields,
  iconButton,
  type LinkOpts,
  NEXT,
  StatusChip,
  stateHref,
  TrustLine,
} from "./parts";
import { CASES, COMPANY, FIRST_QUESTION, PERSON, type StateKey, turnsFor } from "./scenario";

const LATER = "/design-review/oct20#later-pages";

/** One-line "next step" per case, shown in the case header (Direction B keeps a little more context in view). */
const NEXT_STEP: Record<string, string> = {
  attendance: "Next: contact Sarah in writing",
  staffing: "Next: decide whether to request Expert Review",
  probation: "Next: tell HeroOS how the review meeting went",
};

/**
 * Direction B, "Advisory Workspace". Still one page, but with three quiet top
 * tabs (Ask HeroOS, Company Blueprint, the company space), a slim rail of
 * recent cases that collapses to icons, and a case header with the title,
 * status and next step. Case status docks beside the conversation on wide
 * screens and opens as a sheet on small ones.
 */
export function DirectionB({ state, opts }: { state: StateKey; opts: LinkOpts }) {
  const href = (s: StateKey, extra?: Partial<LinkOpts>) => stateHref("b", s, opts, extra);
  const { caseId, turns } = turnsFor(state);
  const caseRef = CASES.find((c) => c.id === caseId) ?? null;
  const inCase = caseRef !== null;
  const opening = state === "understanding";
  const statusOpen = state === "status";
  const caseBase: StateKey = statusOpen ? "warning" : state;
  const firstEntry = state === "empty" || state === "typing";

  const tabs = [
    { label: "Ask HeroOS", href: href("empty"), current: true },
    { label: "Company Blueprint", href: LATER, current: false },
    { label: `${COMPANY.name} space`, href: LATER, current: false },
  ];

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
      <header className="relative z-20 flex h-16 shrink-0 items-center gap-2 border-b border-hero-border bg-white px-2 sm:px-4">
        <a aria-label="Menu and cases" className={`${iconButton} md:hidden`} href={href("history")}>
          <MenuIcon className="size-6" />
        </a>
        <a aria-label="HeroOS: ask a new question" className="inline-flex min-h-11 items-center rounded-lg px-1.5 max-md:mx-auto" href={href("empty")}>
          <BrandMark />
        </a>
        <nav aria-label="HeroOS" className="ml-5 hidden h-full items-stretch gap-1 md:flex">
          {tabs.map((tab) => (
            <a
              aria-current={tab.current ? "page" : undefined}
              className="relative inline-flex items-center px-3 text-[0.9375rem] font-semibold text-hero-muted transition-colors duration-150 hover:text-hero-navy aria-[current=page]:font-bold aria-[current=page]:text-hero-navy aria-[current=page]:after:absolute aria-[current=page]:after:inset-x-3 aria-[current=page]:after:bottom-0 aria-[current=page]:after:h-[3px] aria-[current=page]:after:rounded-t aria-[current=page]:after:bg-hero-yellow"
              href={tab.href}
              key={tab.label}
            >
              {tab.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center md:ml-auto">
          <AccountButton withName />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {opts.rail ? (
          <aside aria-label="Recent cases" className="hidden w-[17rem] shrink-0 flex-col border-r border-hero-border bg-[#f7f6f3] md:flex">
            <div className="flex items-center gap-1.5 p-3">
              <a
                className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-hero-control/60 bg-white px-3 text-[0.9375rem] font-bold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.05)] transition-colors duration-150 hover:bg-hero-blue-tint"
                href={href("empty")}
              >
                <PlusIcon className="size-5" />
                New question
              </a>
              <a aria-label="Collapse the case list" className={iconButton} href={href(state, { rail: false })}>
                <ArrowLeftIcon className="size-5" />
              </a>
            </div>
            {firstEntry ? (
              <div className="mx-3 mt-2 rounded-2xl border border-dashed border-hero-control/60 px-4 py-5 text-center">
                <p className="text-[0.875rem] font-semibold text-hero-navy">No cases yet</p>
                <p className="mt-1 text-[0.8125rem] leading-relaxed text-hero-muted">
                  Each question you ask becomes a case here, named by HeroOS.
                </p>
              </div>
            ) : (
              <>
                <div className="px-3">
                  <CaseSearch />
                </div>
                <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-1 pb-4">
                  <CaseList activeId={statusOpen ? "attendance" : caseId} dense direction="b" opts={opts} />
                </div>
              </>
            )}
          </aside>
        ) : (
          <aside aria-label="Recent cases (collapsed)" className="hidden w-16 shrink-0 flex-col items-center gap-2 border-r border-hero-border bg-[#f7f6f3] py-3 md:flex">
            <a aria-label="Show the case list" className={iconButton} href={href(state, { rail: true })}>
              <ChevronRightIcon className="size-5" />
            </a>
            <a aria-label="New question" className={`${iconButton} border border-hero-control/60 bg-white`} href={href("empty", { rail: false })}>
              <PlusIcon className="size-5" />
            </a>
          </aside>
        )}

        <main className="flex min-w-0 flex-1 flex-col" id="main">
          {inCase ? (
            <div className="flex shrink-0 items-center gap-3 border-b border-hero-border px-3 py-2.5 sm:px-6">
              <div className="min-w-0 flex-1">
                {opening ? (
                  <>
                    <h1 className="sr-only">Opening your case</h1>
                    <span aria-hidden="true" className="dr-shimmer block h-4 w-56 max-w-full rounded-full" />
                    <span aria-hidden="true" className="dr-shimmer mt-2 block h-3 w-40 rounded-full" />
                  </>
                ) : (
                  <>
                    <h1 className={`truncate text-[1.0625rem] font-extrabold tracking-[-0.01em] text-hero-navy ${state === "conversation" ? "dr-title-in" : ""}`}>
                      {caseRef.title}
                    </h1>
                    <p className="truncate text-[0.8125rem] text-hero-muted">
                      Named by HeroOS · <span className="font-semibold text-hero-blue-ink">{NEXT_STEP[caseRef.id]}</span>
                    </p>
                  </>
                )}
              </div>
              {opening ? null : (
                <>
                  <StatusChip compact status={caseRef.status} />
                  <a
                    aria-expanded={statusOpen}
                    aria-label={statusOpen ? "Close case status" : "Open case status"}
                    className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full border border-hero-border px-3 text-[0.875rem] font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint aria-expanded:border-hero-blue aria-expanded:bg-hero-blue-tint"
                    href={statusOpen ? href(caseBase) : href("status")}
                  >
                    <ChecklistIcon className="size-[1.125rem]" />
                    <span className="max-sm:sr-only">Case status</span>
                  </a>
                </>
              )}
            </div>
          ) : null}

          <div className="flex min-h-0 flex-1">
            <section aria-label={inCase ? "Conversation" : "Ask HeroOS"} className="flex min-w-0 flex-1 flex-col">
              {inCase ? (
                <>
                  <div className="dr-log min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,#fbfbfa,#ffffff_30%)]">
                    <div className="mx-auto mb-auto w-full max-w-[44rem] px-3 pb-6 pt-4 sm:px-6 sm:pt-6">
                      <ConversationLog
                        label={`Conversation: ${caseRef.title}`}
                        nextHref={href(NEXT[state])}
                        thinking={opening}
                        turns={turns}
                      />
                    </div>
                  </div>
                  <div className="shrink-0 px-3 pb-3 sm:px-6 sm:pb-5">
                    <div className="mx-auto max-w-[44rem]">
                      <Composer action={href(NEXT[state])} disabled={opening} hidden={hiddenFields(opts)} variant="reply" />
                      <p className="mt-2 text-center text-[0.75rem] text-hero-muted">
                        HeroOS advises. Decisions about your people stay with you.
                      </p>
                    </div>
                  </div>
                </>
              ) : (
                <AskPanel opts={opts} state={state} />
              )}
            </section>

            {statusOpen && caseRef ? (
              <aside aria-labelledby="cs-title" className="dr-panel-in hidden w-[24rem] shrink-0 overflow-y-auto border-l border-hero-border bg-white lg:block">
                <CaseStatusBody caseRef={caseRef} closeHref={href(caseBase)} />
              </aside>
            ) : null}
          </div>
        </main>
      </div>

      {/* Smaller screens: case status as a sheet, the menu as a drawer. */}
      {statusOpen && caseRef ? (
        <div className="absolute inset-0 z-40 lg:hidden">
          <a aria-label="Close case status" className="dr-fade absolute inset-0 bg-hero-navy/25" href={href(caseBase)} />
          <aside
            aria-labelledby="sheet-title"
            className="dr-panel-in absolute inset-x-0 bottom-0 max-h-[88%] overflow-y-auto rounded-t-[1.75rem] bg-white shadow-[0_-20px_60px_-20px_rgb(14_30_61/0.45)] sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[26rem] sm:rounded-none sm:rounded-l-[1.75rem]"
          >
            <CaseStatusBody caseRef={caseRef} closeHref={href(caseBase)} idPrefix="sheet" />
          </aside>
        </div>
      ) : null}
      {state === "history" ? <MobileMenu opts={opts} tabs={tabs} /> : null}
    </div>
  );
}

function AskPanel({ state, opts }: { state: StateKey; opts: LinkOpts }) {
  const returning = state === "history";
  return (
    <div className="relative flex flex-1 flex-col overflow-hidden bg-[radial-gradient(70%_60%_at_50%_0%,#f1f5fd,#ffffff_70%)] px-4 sm:items-center sm:justify-center sm:px-8 sm:pb-16">
      <div className="flex flex-1 flex-col justify-center sm:w-full sm:max-w-[42rem] sm:flex-none">
        <p className="dr-rise text-center text-[0.9375rem] font-semibold text-hero-muted">
          {returning ? `Good afternoon, ${PERSON.first}.` : `Welcome, ${PERSON.first}. Your workspace is ready.`}
        </p>
        <h1 className="dr-rise mt-2 text-center text-[2rem] font-extrabold leading-[1.1] tracking-[-0.03em] text-hero-navy sm:text-[2.625rem]">
          What can HR do for you today?
        </h1>
        <p className="dr-rise-late mx-auto mt-3 max-w-[32rem] text-center text-base leading-relaxed text-hero-muted sm:text-[1.0625rem]">
          Explain the situation in your own words. HeroOS works out the HR side and asks only what it needs.
        </p>
      </div>
      <div className="relative z-10 pb-4 sm:mt-8 sm:w-full sm:max-w-[42rem] sm:pb-0">
        <Composer
          action={stateHref("b", "understanding", opts)}
          hidden={hiddenFields(opts)}
          value={state === "typing" ? FIRST_QUESTION : undefined}
          variant="ask"
        />
        <TrustLine className="mt-3" />
      </div>
    </div>
  );
}

function MobileMenu({ opts, tabs }: { opts: LinkOpts; tabs: { label: string; href: string; current: boolean }[] }) {
  const close = stateHref("b", "empty", opts);
  return (
    <div className="absolute inset-0 z-40 md:hidden">
      <a aria-label="Close the menu" className="dr-fade absolute inset-0 bg-hero-navy/25" href={close} />
      <aside aria-label="Menu" className="dr-from-left absolute inset-y-0 left-0 flex w-[min(20.5rem,88vw)] flex-col bg-[#f7f6f3] shadow-2xl">
        <div className="flex h-16 shrink-0 items-center justify-between px-4">
          <BrandMark />
          <a aria-label="Close the menu" className={iconButton} href={close}>
            <CloseIcon className="size-5" />
          </a>
        </div>
        <nav aria-label="HeroOS" className="px-2">
          <ul className="space-y-0.5">
            {tabs.map((tab) => (
              <li key={tab.label}>
                <a
                  aria-current={tab.current ? "page" : undefined}
                  className="flex min-h-11 items-center rounded-xl px-3 text-[0.9375rem] font-semibold text-hero-navy aria-[current=page]:bg-white aria-[current=page]:font-bold aria-[current=page]:shadow-[inset_3px_0_0_var(--hero-yellow)]"
                  href={tab.href}
                >
                  {tab.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="mx-3 my-3 h-px bg-hero-border" />
        <div className="space-y-3 px-3">
          <a className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-hero-navy px-4 text-[0.9375rem] font-bold text-white" href={close}>
            <PlusIcon className="size-5" />
            New question
          </a>
          <CaseSearch />
        </div>
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-1 pb-4">
          <CaseList activeId={null} direction="b" opts={opts} />
        </div>
      </aside>
    </div>
  );
}
