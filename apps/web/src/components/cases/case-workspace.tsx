"use client";

import { type RefObject, useCallback, useRef, useState } from "react";

import { iconButton, WorkspaceLayout } from "@/components/app/workspace-chrome";
import { WorkspaceHeader, type WorkspaceHeaderData } from "@/components/app/workspace-header";
import { ChevronDownIcon, HelpIcon, PlusIcon } from "@/components/site/icons";
import type { ConversationSummary } from "@/lib/ask/conversation";
import { Notice } from "@/components/ui/notice";
import { caseStatusDot } from "@/lib/workflows/copy";
import type { WorkflowView } from "@/lib/workflows/model";

import { AnswersForm } from "./answers-form";
import { CaseConversationLink } from "./case-conversation-link";
import { type CaseTarget, CaseStatusPanel } from "./case-status-panel";
import { Conversation } from "./conversation";
import { DecisionsPanel } from "./decisions-panel";
import { DocumentsPanel } from "./documents-panel";
import { ProgressionPanel } from "./progression-panel";

/**
 * CASE_READY: one case in the Ask HeroOS workspace (approved Oct 20 design,
 * Page 1). The header names the case and opens its status; the Cases drawer
 * and the account menu are the only ways elsewhere. The page is the case's
 * conversation, then what HeroOS needs to know (the question group in
 * progress), then the official record: next steps (pathway, stages and what
 * can be done now), "Decisions & history" and "Documents" (template previews,
 * never saved or issued).
 *
 * The conversation is the guided workflow's own (no AI until M2-NEW-05/06).
 * The view comes from the API and is replaced by the API's answer after each
 * save; nothing here computes workflow state. A Case Ask HeroOS opened links
 * first to that Ask HeroOS conversation (M2-NEW-07), where it can be read and
 * continued: the chat stays there, apart from the Case's history.
 */

/** The step to open first: the first answerable one with questions left. */
function firstOpenStep(view: WorkflowView): string | undefined {
  const open = view.steps.find(
    (step) => step.available && step.questions.some((question) => view.missing.includes(question.key)),
  );
  return (open ?? view.steps.find((step) => step.available) ?? view.steps[0])?.key;
}

const recordSection =
  "mt-8 scroll-mt-24 rounded-[1.75rem] border border-hero-navy/[0.08] bg-white/90 p-5 shadow-[0_1px_2px_rgb(14_30_61/0.04)] sm:p-7";

/**
 * The case in the header: its name and status, opening the case status. A
 * recorded need for specialist review is never only further down the page:
 * the header says it too.
 */
function CasePill({
  view,
  open,
  onOpen,
  pill,
}: {
  view: WorkflowView;
  open: boolean;
  onOpen: () => void;
  pill: RefObject<HTMLButtonElement | null>;
}) {
  const escalated = (view.progression?.escalations.length ?? 0) > 0;
  const label = escalated ? "Specialist review needed" : view.status.label;
  return (
    <button
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label={`${view.case.title}. ${view.status.label}.${escalated ? " Specialist review needed." : ""} Case status`}
      className="group inline-flex min-h-10 min-w-0 max-w-full items-center gap-2 rounded-full border border-hero-border bg-white/70 px-3.5 shadow-[0_1px_2px_rgb(14_30_61/0.04)] backdrop-blur transition-colors duration-150 hover:bg-white aria-expanded:border-hero-blue/50 aria-expanded:bg-white sm:max-w-[34rem]"
      onClick={onOpen}
      ref={pill}
      type="button"
    >
      <span className="truncate text-[0.9375rem] font-extrabold text-hero-navy">{view.case.title}</span>
      <span
        aria-hidden="true"
        className={`size-2 shrink-0 rounded-full max-sm:hidden ${escalated ? caseStatusDot("held_for_specialist_review") : caseStatusDot(view.status.code)}`}
      />
      <span aria-hidden="true" className="hidden max-w-[14rem] truncate text-[0.8125rem] font-semibold text-hero-muted md:inline">
        {label}
      </span>
      <ChevronDownIcon className="size-4 shrink-0 text-hero-muted transition-transform duration-200 group-aria-expanded:rotate-180" />
    </button>
  );
}

export function CaseWorkspace({
  header,
  initialView,
  askConversation = null,
  fetcher,
  documentsFetcher,
}: {
  /** The workspace header's data for this Company (with its case list). */
  header: WorkspaceHeaderData;
  initialView: WorkflowView;
  /** The Ask HeroOS conversation this Case started from, for its administrators. */
  askConversation?: ConversationSummary | null;
  fetcher?: typeof fetch;
  /** The Documents section's own reads and previews (tests); the page's fetch by default. */
  documentsFetcher?: typeof fetch;
}) {
  const [view, setView] = useState(initialView);
  const [selected, setSelected] = useState(() => firstOpenStep(initialView));
  const [statusOpen, setStatusOpen] = useState(false);
  const pill = useRef<HTMLButtonElement>(null);

  const companyId = header.companyId;
  const caseId = view.case.id;
  const step = view.steps.find((item) => item.key === selected) ?? view.steps[0];
  const stepIndex = step ? view.steps.indexOf(step) : -1;
  const nextStep = view.steps
    .slice(stepIndex + 1)
    .find((item) => item.available && item.questions.some((question) => view.missing.includes(question.key)));
  const stage = view.progression?.stages.find((item) => item.status === "in_progress") ?? null;

  const choose = (key: string) => {
    setSelected(key);
    requestAnimationFrame(() => document.getElementById("composer-heading")?.focus());
  };

  const closeStatus = useCallback(() => setStatusOpen(false), []);
  // From the case status to a part of the page: the panel closes (focus returns to the case), then the page scrolls.
  const go = useCallback(({ target, step: stepKey }: CaseTarget) => {
    if (stepKey) setSelected(stepKey);
    setStatusOpen(false);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => document.getElementById(target)?.scrollIntoView?.({ block: "start" })),
    );
  }, []);

  // The Cases drawer shows this case's live status and update time.
  const cases =
    header.cases?.map((item) =>
      item.id === caseId ? { ...item, status: view.status, updatedAt: view.case.updatedAt } : item,
    ) ?? null;
  const ask = `/workspaces/${encodeURIComponent(companyId)}`;

  return (
    <WorkspaceLayout
      header={
        <WorkspaceHeader
          actions={
            <a aria-label="New question" className={`${iconButton} max-sm:hidden`} href={ask} title="New question">
              <PlusIcon className="size-5" />
            </a>
          }
          center={<CasePill onOpen={() => setStatusOpen(true)} open={statusOpen} pill={pill} view={view} />}
          currentCaseId={caseId}
          data={{ ...header, cases }}
        />
      }
      overlay={
        statusOpen ? (
          <CaseStatusPanel companyName={header.companyName} onClose={closeStatus} onGo={go} returnTo={pill} view={view} />
        ) : null
      }
      quiet
    >
      <div className="mx-auto w-full max-w-[46rem] px-4 pb-10 pt-3 sm:px-6 sm:pt-7">
        <h1 className="sr-only">{view.case.title}</h1>
        {view.sensitiveScreening === "synthetic_demo" ? (
          <p className="mb-6 rounded-xl border border-hero-border bg-white/80 px-4 py-2.5 text-sm font-semibold text-hero-navy" role="note">
            Demo environment: use made-up examples only, never real employee information.
          </p>
        ) : null}

        {askConversation ? <CaseConversationLink companyId={companyId} conversation={askConversation} /> : null}

        <section aria-labelledby="conversation-heading" className="scroll-mt-24" id="guided-conversation">
          <h2 className="sr-only" id="conversation-heading">
            Conversation
          </h2>
          <Conversation label={`Conversation: ${view.case.title}`} messages={view.conversation} />
        </section>

        <section
          aria-label="Your answers"
          className="mt-9 scroll-mt-24 rounded-[1.75rem] border border-hero-navy/[0.12] bg-white p-5 shadow-[0_1px_2px_rgb(14_30_61/0.05),0_16px_36px_-24px_rgb(14_30_61/0.4)] sm:p-6"
          id="your-answers"
        >
          <p className="flex items-center gap-1.5 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted">
            <HelpIcon className="size-3.5" />
            HeroOS needs to know
          </p>
          <nav aria-label="Question groups" className="-mx-1 mb-5 mt-3 overflow-x-auto px-1 pb-1">
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
                          ? "border-hero-blue/60 bg-[#f5f8fe] text-hero-navy"
                          : "border-hero-navy/[0.12] bg-white text-hero-navy hover:bg-hero-navy/[0.03]"
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
              <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy outline-none" id="composer-heading" tabIndex={-1}>
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
              demoOnly={view.sensitiveScreening === "synthetic_demo"}
              fetcher={fetcher}
              key={step.key}
              next={nextStep ? { title: nextStep.title, go: () => choose(nextStep.key) } : null}
              onSaved={setView}
              revision={view.workflow.revision}
              step={step}
            />
          ) : null}
        </section>

        <section aria-labelledby="next-steps-heading" className={recordSection} id="next-steps">
          <ProgressionPanel caseId={caseId} companyId={companyId} fetcher={fetcher} onUpdated={setView} view={view} />
        </section>

        <section aria-labelledby="decisions-heading" className={recordSection} id="decisions-history">
          <DecisionsPanel caseId={caseId} companyId={companyId} fetcher={fetcher} onUpdated={setView} view={view} />
        </section>

        {view.canEdit ? (
          <section aria-labelledby="documents-heading" className={recordSection} id="documents">
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

    </WorkspaceLayout>
  );
}
