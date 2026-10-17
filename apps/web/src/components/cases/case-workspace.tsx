"use client";

import { useState } from "react";

import { ArrowLeftIcon, CaseIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { caseStatusTone, formatDay } from "@/lib/workflows/copy";
import type { CaseSummary, WorkflowView } from "@/lib/workflows/model";

import { AnswersForm } from "./answers-form";
import { CaseContextPanel } from "./case-context-panel";
import { Conversation } from "./conversation";
import { ProgressionPanel } from "./progression-panel";

/**
 * CASE_READY: the guided Case workspace. Left: the Company's Disciplinary
 * Cases. Centre: the conversation, the next steps (workflow progression:
 * pathway, stages and what can be done now) and, for administrators, the
 * question groups (one step at a time). Right (below the conversation on
 * smaller screens): progress, hold, jurisdiction, cautions, facts, missing and
 * uncertain answers, and the case and progression history.
 *
 * The view comes from the API and is replaced by the API's answer after each
 * save; nothing here computes workflow state.
 */

/** The step to open first: the first answerable one with questions left. */
function firstOpenStep(view: WorkflowView): string | undefined {
  const open = view.steps.find(
    (step) => step.available && step.questions.some((question) => view.missing.includes(question.key)),
  );
  return (open ?? view.steps.find((step) => step.available) ?? view.steps[0])?.key;
}
export function CaseWorkspace({
  companyId,
  cases,
  initialView,
  fetcher,
}: {
  companyId: string;
  cases: CaseSummary[];
  initialView: WorkflowView;
  fetcher?: typeof fetch;
}) {
  const [view, setView] = useState(initialView);
  const [selected, setSelected] = useState(() => firstOpenStep(initialView));
  const casesHref = `/workspaces/${encodeURIComponent(companyId)}/cases`;
  const caseId = view.case.id;
  const step = view.steps.find((item) => item.key === selected) ?? view.steps[0];
  const total = view.asked.length;
  const answered = total - view.missing.length;
  const stepIndex = step ? view.steps.indexOf(step) : -1;
  const nextStep = view.steps
    .slice(stepIndex + 1)
    .find((item) => item.available && item.questions.some((question) => view.missing.includes(question.key)));
  const choose = (key: string) => {
    setSelected(key);
    requestAnimationFrame(() => document.getElementById("composer-heading")?.focus());
  };
  // The sidebar shows the current Case's live title and status.
  const sidebar = cases.some((item) => item.id === caseId)
    ? cases.map((item) => (item.id === caseId ? { ...item, status: view.status } : item))
    : cases;

  return (
    <div className="mx-auto w-full max-w-[1240px] lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)] xl:grid-cols-[15.5rem_minmax(0,1fr)_20rem]">
      <aside
        aria-label="Disciplinary cases"
        className="hidden border-r border-hero-border lg:row-span-2 lg:block xl:row-span-1"
      >
        <div className="sticky top-[72px] flex max-h-[calc(100vh-72px)] flex-col gap-4 overflow-y-auto px-4 py-6">
          <a
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-sm font-bold text-hero-blue-ink hover:underline"
            href={`/workspaces/${encodeURIComponent(companyId)}`}
          >
            <ArrowLeftIcon className="size-4" />
            Workspace home
          </a>
          <div className="flex items-center justify-between gap-2">
            <a className="text-base font-extrabold text-hero-navy hover:underline" href={casesHref}>
              Disciplinary cases
            </a>
            {view.canEdit ? (
              <a
                className="inline-flex min-h-9 items-center rounded-full border border-hero-control bg-white px-3 text-sm font-bold text-hero-navy hover:bg-hero-blue-tint"
                href={`${casesHref}/new`}
              >
                New
              </a>
            ) : null}
          </div>
          <nav aria-label="Cases">
            <ul className="flex flex-col gap-1">
              {sidebar.map((item) => {
                const current = item.id === caseId;
                return (
                  <li key={item.id}>
                    <a
                      aria-current={current ? "page" : undefined}
                      className={`flex flex-col gap-1 rounded-xl px-3 py-2.5 text-sm transition-colors duration-150 ${
                        current ? "bg-hero-blue-tint text-hero-navy" : "text-hero-navy hover:bg-hero-bg"
                      }`}
                      href={`${casesHref}/${encodeURIComponent(item.id)}`}
                    >
                      <span className="line-clamp-2 break-words font-semibold">{item.title}</span>
                      <span className="text-xs text-hero-muted">{item.status.label}</span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>
      </aside>

      <div className="min-w-0 px-4 py-6 sm:px-6 sm:py-8 lg:col-start-2 lg:px-8">
        <a
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-sm font-bold text-hero-blue-ink hover:underline lg:hidden"
          href={casesHref}
        >
          <ArrowLeftIcon className="size-4" />
          All Disciplinary cases
        </a>
        <header className="mt-2 flex flex-col gap-3 border-b border-hero-border pb-5 lg:mt-0">
          <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">
            <CaseIcon className="size-4" />
            {view.workflow.title} · guided workflow, no AI
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="min-w-0 break-words text-[1.625rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy sm:text-[2rem]">
              {view.case.title}
            </h1>
            <StatusBadge tone={caseStatusTone(view.status.code)}>{view.status.label}</StatusBadge>
          </div>
          <p className="text-sm text-hero-muted">
            Created <time dateTime={view.case.createdAt}>{formatDay(view.case.createdAt)}</time> · {answered} of {total}{" "}
            intake questions answered
            <a className="ml-2 font-bold text-hero-blue-ink underline xl:hidden" href="#case-details">
              Progress and details
            </a>
          </p>
          {view.progression && view.progression.status.code !== "unavailable" ? (
            <p className="text-sm font-semibold text-hero-navy" data-testid="current-stage">
              Next steps: {view.progression.status.label}
              {view.progression.stages.find((stage) => stage.status === "in_progress")
                ? ` · ${view.progression.stages.find((stage) => stage.status === "in_progress")!.title}`
                : ""}
              <a className="ml-2 font-bold text-hero-blue-ink underline" href="#next-steps">
                Go to next steps
              </a>
            </p>
          ) : null}
          {view.sensitiveScreening === "synthetic_demo" ? (
            <p className="text-sm font-semibold text-hero-navy">
              Demo environment: use made-up examples only, never real employee information.
            </p>
          ) : null}
        </header>

        <section aria-labelledby="conversation-heading" className="mt-6">
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
          className="mt-8 rounded-3xl border border-hero-border bg-white p-5 shadow-hero-card sm:p-7"
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
      </div>

      <aside
        aria-label="Case details"
        className="border-t border-hero-border bg-hero-surface/40 px-4 py-6 sm:px-6 lg:col-start-2 lg:px-8 xl:col-start-3 xl:row-start-1 xl:border-l xl:border-t-0 xl:px-5"
        id="case-details"
      >
        <div className="xl:sticky xl:top-[72px] xl:max-h-[calc(100vh-72px)] xl:overflow-y-auto xl:py-2">
          <CaseContextPanel view={view} />
        </div>
      </aside>
    </div>
  );
}
