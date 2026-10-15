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

/**
 * CASE_READY: the guided Case workspace. Left: the Company's Disciplinary
 * Cases. Centre: the conversation and, for administrators, the composer.
 * Right (below the conversation on smaller screens): progress, jurisdiction
 * readiness, known facts and missing information.
 *
 * The view comes from the API and is replaced by the API's answer after each
 * save; nothing here computes workflow state.
 */
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
  const casesHref = `/workspaces/${encodeURIComponent(companyId)}/cases`;
  const caseId = view.case.id;
  const step = view.steps[0];
  const missingInStep = step ? step.questions.filter((question) => view.missing.includes(question.key)).length : 0;
  const answered = view.steps.reduce((sum, s) => sum + s.questions.length, 0) - view.missing.length;
  const total = view.steps.reduce((sum, s) => sum + s.questions.length, 0);
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
            initial questions answered
            <a className="ml-2 font-bold text-hero-blue-ink underline xl:hidden" href="#case-details">
              Progress and details
            </a>
          </p>
        </header>

        <section aria-labelledby="conversation-heading" className="mt-6">
          <h2 className="sr-only" id="conversation-heading">
            Conversation
          </h2>
          <Conversation messages={view.conversation} />
        </section>

        <section
          aria-label="Your answers"
          className="mt-8 rounded-3xl border border-hero-border bg-white p-5 shadow-hero-card sm:p-7"
        >
          {step && view.canEdit ? (
            <AnswersForm
              answers={view.answers}
              caseId={caseId}
              companyId={companyId}
              fetcher={fetcher}
              missingCount={missingInStep}
              onSaved={setView}
              revision={view.workflow.revision}
              step={step}
            />
          ) : (
            <Notice title="View only">
              You can follow this case. Only company administrators can add or change its answers.
            </Notice>
          )}
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
