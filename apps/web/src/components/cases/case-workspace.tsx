"use client";

import { type KeyboardEvent, type MouseEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ArrowLeftIcon,
  CaseIcon,
  ChecklistIcon,
  ChevronRightIcon,
  CloseIcon,
  MenuIcon,
  PlusIcon,
} from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { ASSISTANT_HIDDEN, type AssistantLoad } from "@/lib/assistant/model";
import { caseStatusTone, formatDay } from "@/lib/workflows/copy";
import type { CaseSummary, WorkflowView } from "@/lib/workflows/model";

import { AnswersForm } from "./answers-form";
import { CaseContextPanel } from "./case-context-panel";
import { CaseSummaryPanel, type WorkflowTarget } from "./case-summary-panel";
import { Conversation } from "./conversation";
import { DecisionsPanel } from "./decisions-panel";
import { DocumentsPanel } from "./documents-panel";
import { HannahAvatar, HannahChat } from "./hannah-chat";
import { ProgressionPanel } from "./progression-panel";

/**
 * CASE_READY: the Case workspace (JJ design review, screen 10). Left: the
 * Company's Disciplinary Cases. Centre: the case header, then the
 * conversation with Hannah (the AI demo, when the API says this administrator
 * can use it) or the guided case workflow, one tab each. Right: the case at a
 * glance (status, stage, the next official step, recorded facts) above the
 * full case details. On smaller screens the case list and the details open as
 * panels from the header, so the conversation keeps the full width.
 *
 * The guided case workflow is the official record and is unchanged: the
 * guided conversation, the next steps (pathway, stages and what can be done
 * now), for administrators the question groups (one step at a time),
 * "Decisions & history" (employer records, corrections and the unified case
 * history) and "Documents" (template previews, never saved or issued). It is
 * the only view when Hannah is switched off, and one tab away when she isn't.
 *
 * Hannah's conversation is never saved and never changes the Case. The view
 * comes from the API and is replaced by the API's answer after each save;
 * nothing here computes workflow state.
 */

type Tab = "hannah" | "workflow";
type Drawer = "cases" | "details" | null;

/** The step to open first: the first answerable one with questions left. */
function firstOpenStep(view: WorkflowView): string | undefined {
  const open = view.steps.find(
    (step) => step.available && step.questions.some((question) => view.missing.includes(question.key)),
  );
  return (open ?? view.steps.find((step) => step.available) ?? view.steps[0])?.key;
}

const drawerClose =
  "inline-flex size-10 items-center justify-center rounded-full text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint";
const headerToggle =
  "inline-flex min-h-10 items-center gap-1.5 rounded-full border border-hero-control bg-white px-3.5 text-sm font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint";

export function CaseWorkspace({
  companyId,
  cases,
  initialView,
  assistant = ASSISTANT_HIDDEN,
  fetcher,
  documentsFetcher,
  assistantFetcher,
}: {
  companyId: string;
  cases: CaseSummary[];
  initialView: WorkflowView;
  /** The Hannah AI demo's status, read by the page with the Case (hidden when absent). */
  assistant?: AssistantLoad;
  fetcher?: typeof fetch;
  /** The Documents section's own reads and previews (tests); the page's fetch by default. */
  documentsFetcher?: typeof fetch;
  /** The Hannah AI demo's own requests (tests); the page's fetch by default. */
  assistantFetcher?: typeof fetch;
}) {
  const [view, setView] = useState(initialView);
  const [selected, setSelected] = useState(() => firstOpenStep(initialView));
  // Only administrators may use Hannah (the API refuses everyone else too).
  const [hannah, setHannah] = useState<AssistantLoad>(initialView.canEdit ? assistant : ASSISTANT_HIDDEN);
  const [chosen, setChosen] = useState<Tab | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const workflowRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);

  const casesHref = `/workspaces/${encodeURIComponent(companyId)}/cases`;
  const caseId = view.case.id;
  const step = view.steps.find((item) => item.key === selected) ?? view.steps[0];
  const total = view.asked.length;
  const answered = total - view.missing.length;
  const stepIndex = step ? view.steps.indexOf(step) : -1;
  const nextStep = view.steps
    .slice(stepIndex + 1)
    .find((item) => item.available && item.questions.some((question) => view.missing.includes(question.key)));
  const stage = view.progression?.stages.find((item) => item.status === "in_progress") ?? null;

  // Hannah leads when she can answer; otherwise the guided workflow does, and a switched-off demo has no tab.
  const tabs = hannah.state !== "hidden";
  const tab: Tab = tabs
    ? (chosen ?? (hannah.state === "ready" && hannah.status.available ? "hannah" : "workflow"))
    : "workflow";

  const show = (next: Tab) => {
    setChosen(next);
    // The conversation is laid out from the top of the screen on large screens.
    if (next === "hannah" && window.matchMedia?.("(min-width: 1024px)")?.matches) window.scrollTo({ top: 0 });
  };

  const choose = (key: string) => {
    setSelected(key);
    requestAnimationFrame(() => document.getElementById("composer-heading")?.focus());
  };

  /** The guided workflow, scrolled to one of its sections. */
  const reveal = useCallback((target: HTMLElement | null) => {
    setChosen("workflow");
    setDrawer(null);
    requestAnimationFrame(() => target?.scrollIntoView?.({ block: "start" }));
  }, []);

  const openWorkflow = ({ target, step: stepKey }: WorkflowTarget) => {
    if (stepKey) setSelected(stepKey);
    setChosen("workflow");
    setDrawer(null);
    requestAnimationFrame(() => document.getElementById(target)?.scrollIntoView?.({ block: "start" }));
  };

  // A link into the guided workflow (e.g. "#case-history") opens its tab first; so does such a URL.
  const followLink = (event: MouseEvent<HTMLDivElement>) => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
    const id = link?.getAttribute("href")?.slice(1);
    const target = id ? document.getElementById(id) : null;
    if (target && workflowRef.current?.contains(target)) reveal(target);
  };
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    const target = id ? document.getElementById(id) : null;
    if (target && workflowRef.current?.contains(target)) reveal(target);
  }, [reveal]);

  // The case list and the details open as panels on smaller screens: Escape closes them.
  useEffect(() => {
    if (drawer === null) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setDrawer(null);
    };
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => document.getElementById(`${drawer}-close`)?.focus());
    return () => document.removeEventListener("keydown", onKey);
  }, [drawer]);

  const openDrawer = (which: Exclude<Drawer, null>, button: HTMLButtonElement) => {
    toggleRef.current = button;
    setDrawer(which);
  };
  const closeDrawer = () => {
    setDrawer(null);
    requestAnimationFrame(() => toggleRef.current?.focus());
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next: Tab =
      event.key === "Home" ? "hannah" : event.key === "End" ? "workflow" : tab === "hannah" ? "workflow" : "hannah";
    show(next);
    requestAnimationFrame(() => document.getElementById(`case-tab-${next}`)?.focus());
  };

  // The sidebar shows the current Case's live title, status and update time.
  const sidebar = cases.some((item) => item.id === caseId)
    ? cases.map((item) =>
        item.id === caseId ? { ...item, status: view.status, updatedAt: view.case.updatedAt } : item,
      )
    : cases;

  return (
    <div
      className={`mx-auto w-full max-w-[1240px] lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_21rem] ${
        // The conversation fills the screen (its messages scroll, the composer stays put); the workflow is a page.
        tab === "hannah" ? "lg:h-[calc(100dvh-72px)] lg:grid-rows-[minmax(0,1fr)]" : ""
      }`}
      onClickCapture={followLink}
    >
      {drawer ? (
        <div
          aria-hidden="true"
          className={`fixed inset-0 z-[45] bg-hero-navy/35 ${drawer === "cases" ? "lg:hidden" : "xl:hidden"}`}
          onClick={closeDrawer}
        />
      ) : null}

      <aside
        aria-label="Disciplinary cases"
        className={`${
          drawer === "cases" ? "fixed inset-y-0 left-0 z-50 flex w-[min(20rem,88vw)] shadow-2xl" : "hidden"
        } flex-col overflow-y-auto border-r border-hero-border bg-white lg:sticky lg:inset-auto lg:top-[72px] lg:z-auto lg:flex lg:h-[calc(100dvh-72px)] lg:w-auto lg:self-start lg:bg-white/60 lg:shadow-none`}
        id="case-list"
      >
        <div className="flex items-center justify-between px-4 pt-3 lg:hidden">
          <p className="text-sm font-extrabold text-hero-navy">Cases</p>
          <button aria-label="Close the case list" className={drawerClose} id="cases-close" onClick={closeDrawer} type="button">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="flex flex-col gap-4 px-4 py-5">
          {view.canEdit ? (
            <a
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-hero-blue px-4 text-base font-bold text-white shadow-[0_8px_20px_-12px_rgb(61_107_196/0.9)] transition-colors duration-150 hover:bg-hero-blue-ink"
              href={`${casesHref}/new`}
            >
              <PlusIcon className="size-5" />
              New case
            </a>
          ) : null}
          <div className="flex items-center justify-between gap-2">
            <a className="text-sm font-extrabold text-hero-navy hover:underline" href={casesHref}>
              Disciplinary cases
            </a>
            <span className="text-xs font-semibold text-hero-muted">{sidebar.length}</span>
          </div>
          <nav aria-label="Cases">
            <ul className="flex flex-col gap-2">
              {sidebar.map((item) => {
                const current = item.id === caseId;
                return (
                  <li key={item.id}>
                    <a
                      aria-current={current ? "page" : undefined}
                      className={`flex items-start gap-2 rounded-2xl border px-3.5 py-3 transition-colors duration-150 ${
                        current
                          ? "border-[#bcd2f5] bg-hero-blue-tint shadow-[inset_3px_0_0_var(--hero-blue)]"
                          : "border-hero-border bg-white hover:border-[#cfe0f8] hover:bg-hero-blue-tint/40"
                      }`}
                      href={`${casesHref}/${encodeURIComponent(item.id)}`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-2 break-words text-[0.9375rem] font-bold leading-snug text-hero-navy">
                          {item.title}
                        </span>
                        <span className="mt-0.5 block text-xs text-hero-muted">
                          Updated <time dateTime={item.updatedAt}>{formatDay(item.updatedAt)}</time>
                        </span>
                        <span className="mt-2 block">
                          <StatusBadge tone={caseStatusTone(item.status.code)}>{item.status.label}</StatusBadge>
                        </span>
                      </span>
                      <ChevronRightIcon className="mt-0.5 size-4 shrink-0 text-hero-blue-ink" />
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
          <a
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-sm font-bold text-hero-blue-ink hover:underline"
            href={`/workspaces/${encodeURIComponent(companyId)}`}
          >
            <ArrowLeftIcon className="size-4" />
            Workspace home
          </a>
        </div>
      </aside>

      <div className={`flex min-w-0 flex-col bg-white ${tab === "hannah" ? "lg:min-h-0" : ""}`}>
        <header className="shrink-0 border-b border-hero-border px-4 pt-4 sm:px-6 lg:px-8 lg:pt-6">
          <div className="mb-3 flex items-center justify-between gap-2 xl:hidden">
            <button
              aria-controls="case-list"
              aria-expanded={drawer === "cases"}
              className={`${headerToggle} lg:invisible`}
              onClick={(event) => openDrawer("cases", event.currentTarget)}
              type="button"
            >
              <MenuIcon className="size-4" />
              Cases
            </button>
            <button
              aria-controls="case-details"
              aria-expanded={drawer === "details"}
              className={headerToggle}
              onClick={(event) => openDrawer("details", event.currentTarget)}
              type="button"
            >
              Case details
              <ChevronRightIcon className="size-4" />
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="min-w-0 break-words text-[1.5rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy sm:text-[1.875rem]">
              {view.case.title}
            </h1>
            <StatusBadge tone={caseStatusTone(view.status.code)}>{view.status.label}</StatusBadge>
          </div>
          <p className="mt-1.5 text-sm text-hero-muted">
            {view.workflow.title} · Created <time dateTime={view.case.createdAt}>{formatDay(view.case.createdAt)}</time>{" "}
            · {answered} of {total} intake questions answered
            {stage ? ` · ${stage.title}` : ""}
          </p>
          {view.sensitiveScreening === "synthetic_demo" ? (
            <p className="mt-1 text-sm font-semibold text-hero-navy">
              Demo environment: use made-up examples only, never real employee information.
            </p>
          ) : null}
          {tabs ? (
            <div aria-label="Case views" className="-mb-px mt-4 flex gap-1 overflow-x-auto" role="tablist">
              {(["hannah", "workflow"] as const).map((key) => {
                const active = tab === key;
                return (
                  <button
                    aria-controls={`case-panel-${key}`}
                    aria-label={key === "hannah" ? "Chat with Hannah (AI demo)" : "Guided case workflow"}
                    aria-selected={active}
                    className={`inline-flex min-h-12 shrink-0 items-center gap-2 border-b-[3px] px-2.5 text-sm font-bold sm:px-3 sm:text-[0.9375rem] transition-colors duration-150 ${
                      active
                        ? "border-hero-blue text-hero-navy"
                        : "border-transparent text-hero-muted hover:border-hero-border hover:text-hero-navy"
                    }`}
                    id={`case-tab-${key}`}
                    key={key}
                    onClick={() => show(key)}
                    onKeyDown={onTabKey}
                    role="tab"
                    tabIndex={active ? 0 : -1}
                    type="button"
                  >
                    {/* Shorter words on phones, so both tabs fit; the names stay the same (aria-label). */}
                    {key === "hannah" ? (
                      <>
                        <HannahAvatar size="sm" />
                        <span className="sm:hidden">Hannah</span>
                        <span className="hidden sm:inline">Chat with Hannah</span>
                        <span className="rounded-full bg-hero-yellow-tint px-2 py-0.5 text-xs font-bold text-hero-navy">
                          AI demo
                        </span>
                      </>
                    ) : (
                      <>
                        <ChecklistIcon className="size-5" />
                        <span className="sm:hidden">Guided workflow</span>
                        <span className="hidden sm:inline">Guided case workflow</span>
                      </>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="pb-4" />
          )}
        </header>

        {tabs ? (
          <div
            aria-labelledby="case-tab-hannah"
            className="flex min-h-[calc(100dvh-4rem)] flex-col lg:min-h-0 lg:flex-1"
            hidden={tab !== "hannah"}
            id="case-panel-hannah"
            role="tabpanel"
          >
            <HannahChat
              caseId={caseId}
              companyId={companyId}
              fetcher={assistantFetcher}
              load={hannah}
              onLoad={setHannah}
              onOpenWorkflow={() => openWorkflow({ target: "case-panel-workflow" })}
            />
          </div>
        ) : null}

        <div
          {...(tabs ? { role: "tabpanel", "aria-labelledby": "case-tab-workflow" } : {})}
          hidden={tab !== "workflow"}
          id="case-panel-workflow"
          ref={workflowRef}
        >
          <div className="px-4 py-6 sm:px-6 lg:px-8">
            <div className="flex flex-col gap-2 border-b border-hero-border pb-5">
              <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">
                <CaseIcon className="size-4" />
                {view.workflow.title} · guided workflow, no AI
              </p>
              <p className="text-sm leading-relaxed text-hero-navy/85">
                The official case record: HeroOS&apos;s fixed questions, your saved answers, the next steps, decisions
                and documents.
                {view.decisions ? (
                  <a className="ml-2 font-bold text-hero-blue-ink underline" href="#decisions-history">
                    Decisions &amp; history
                  </a>
                ) : null}
                {view.canEdit ? (
                  <a className="ml-2 font-bold text-hero-blue-ink underline" href="#documents">
                    Documents
                  </a>
                ) : null}
              </p>
              {view.progression && view.progression.status.code !== "unavailable" ? (
                <p className="text-sm font-semibold text-hero-navy" data-testid="current-stage">
                  Next steps: {view.progression.status.label}
                  {view.progression.escalations.length > 0 ? " · Specialist review needed" : ""}
                  {stage ? ` · ${stage.title}` : ""}
                  <a className="ml-2 font-bold text-hero-blue-ink underline" href="#next-steps">
                    Go to next steps
                  </a>
                </p>
              ) : null}
            </div>

            <section aria-labelledby="conversation-heading" className="mt-6 scroll-mt-24" id="guided-conversation">
              <h2 className="sr-only" id="conversation-heading">
                Conversation
              </h2>
              <Conversation messages={view.conversation} />
            </section>

            <section
              aria-labelledby="next-steps-heading"
              className="mt-8 scroll-mt-24 rounded-3xl border border-hero-border bg-hero-surface/40 p-5 sm:p-7"
              id="next-steps"
            >
              <ProgressionPanel caseId={caseId} companyId={companyId} fetcher={fetcher} onUpdated={setView} view={view} />
            </section>

            <section
              aria-label="Your answers"
              className="mt-8 scroll-mt-24 rounded-3xl border border-hero-border bg-white p-5 shadow-hero-card sm:p-7"
              id="your-answers"
            >
              <nav aria-label="Question groups" className="-mx-1 mb-6 overflow-x-auto px-1 pb-1">
                <ol className="flex min-w-max gap-2 sm:min-w-0 sm:flex-wrap">
                  {view.steps.map((item, index) => {
                    const progress = view.progress.find((entry) => entry.key === item.key);
                    const current = item.key === step?.key;
                    return (
                      <li key={item.key}>
                        <button
                          aria-current={current ? "step" : undefined}
                          className={`flex min-h-11 flex-col items-start rounded-2xl border px-3.5 py-2 text-left transition-colors duration-150 ${
                            current
                              ? "border-hero-blue bg-hero-blue-tint text-hero-navy"
                              : "border-hero-border bg-white text-hero-navy hover:bg-hero-bg"
                          }`}
                          onClick={() => choose(item.key)}
                          type="button"
                        >
                          <span className="text-sm font-bold">
                            {index + 1}. {item.title}
                          </span>
                          <span className="text-xs text-hero-muted">
                            {item.available ? (progress?.detail ?? "") : "Not available now"}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </nav>
              {!view.canEdit ? (
                <Notice title="View only">
                  You can follow this case. Only company administrators can add or change its answers.
                </Notice>
              ) : step && !step.available ? (
                <div>
                  <h2
                    className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy outline-none"
                    id="composer-heading"
                    tabIndex={-1}
                  >
                    {step.title}
                  </h2>
                  <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">{step.intro}</p>
                  <Notice className="mt-4" title="Not available right now">
                    {step.unavailableReason ?? "This step can't be answered in the case's current state."}
                  </Notice>
                </div>
              ) : step ? (
                <AnswersForm
                  answers={view.answers}
                  caseId={caseId}
                  companyId={companyId}
                  fetcher={fetcher}
                  key={step.key}
                  demoOnly={view.sensitiveScreening === "synthetic_demo"}
                  next={nextStep ? { title: nextStep.title, go: () => choose(nextStep.key) } : null}
                  onSaved={setView}
                  revision={view.workflow.revision}
                  step={step}
                />
              ) : null}
            </section>

            <section
              aria-labelledby="decisions-heading"
              className="mt-8 scroll-mt-24 rounded-3xl border border-hero-border bg-hero-surface/40 p-5 sm:p-7"
              id="decisions-history"
            >
              <DecisionsPanel caseId={caseId} companyId={companyId} fetcher={fetcher} onUpdated={setView} view={view} />
            </section>

            {view.canEdit ? (
              <section
                aria-labelledby="documents-heading"
                className="mt-8 scroll-mt-24 rounded-3xl border border-hero-border bg-hero-surface/40 p-5 sm:p-7"
                id="documents"
              >
                <DocumentsPanel
                  caseId={caseId}
                  companyId={companyId}
                  fetcher={documentsFetcher}
                  revision={view.workflow.revision}
                  stage={stage?.title ?? null}
                />
              </section>
            ) : null}
          </div>
        </div>
      </div>

      <aside
        aria-label="Case details"
        className={`${
          drawer === "details" ? "fixed inset-y-0 right-0 z-50 block w-[min(24rem,92vw)] shadow-2xl" : "hidden"
        } overflow-y-auto border-l border-hero-border bg-hero-bg xl:sticky xl:inset-auto xl:top-[72px] xl:z-auto xl:block xl:h-[calc(100dvh-72px)] xl:w-auto xl:self-start xl:bg-white/60 xl:shadow-none`}
        id="case-details"
      >
        <div className="flex items-center justify-between px-4 pt-3 xl:hidden">
          <p className="text-sm font-extrabold text-hero-navy">Case details</p>
          <button aria-label="Close the case details" className={drawerClose} id="details-close" onClick={closeDrawer} type="button">
            <CloseIcon className="size-5" />
          </button>
        </div>
        <div className="flex flex-col gap-4 px-4 py-5 xl:px-5">
          <CaseSummaryPanel onOpenWorkflow={openWorkflow} view={view} />
          <div className="rounded-2xl border border-hero-border bg-white p-4 shadow-hero-card">
            <CaseContextPanel view={view} />
          </div>
        </div>
      </aside>
    </div>
  );
}
