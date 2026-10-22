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
import { ConversationMessage } from "./conversation";
import { type CaseTarget, CaseStatusPanel } from "./case-status-panel";
import { DecisionsPanel } from "./decisions-panel";
import { DocumentsPanel } from "./documents-panel";
import { ProgressionPanel } from "./progression-panel";

/**
 * CASE_READY: one case's record (approved Oct 20 design, Page 1). The header
 * names the case and opens its status; the Cases drawer and the account menu
 * are the only ways elsewhere.
 *
 * The Case is chat-first (M2-NEW-08): its conversation is Ask HeroOS, where
 * the founder explains the situation, HeroOS asks one useful question at a
 * time and the Case's formal steps appear inline. This page is the secondary,
 * administrative surface: "Continue with HeroOS" first, then the case details
 * to review or correct (the same structured answers, collapsed until asked
 * for), the formal workflow (pathway, stages and what can be done now: the
 * same controls Ask HeroOS offers inline), "Decisions & history" and
 * "Documents" (template previews, never saved or issued). It is never a
 * second conversation: the guided workflow's old chat thread isn't shown.
 *
 * The view comes from the API and is replaced by the API's answer after each
 * save; nothing here computes workflow state. Both surfaces write through the
 * same routes, validation and Case mutation service.
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
 * The case in the header: its name and status, opening the case status. The
 * status is the Case's own (M2-NEW-08): a step the progression rules held for
 * specialist review is attention on that step (the case status and Next steps
 * say so), never the whole Case's status.
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
  const label = view.status.label;
  return (
    <button
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label={`${view.case.title}. ${view.status.label}. Case status`}
      className="group inline-flex min-h-10 min-w-0 max-w-full items-center gap-2 rounded-full border border-hero-border bg-white/70 px-3.5 shadow-[0_1px_2px_rgb(14_30_61/0.04)] backdrop-blur transition-colors duration-150 hover:bg-white aria-expanded:border-hero-blue/50 aria-expanded:bg-white sm:max-w-[34rem]"
      onClick={onOpen}
      ref={pill}
      type="button"
    >
      <span className="truncate text-[0.9375rem] font-extrabold text-hero-navy">{view.case.title}</span>
      <span
        aria-hidden="true"
        className={`size-2 shrink-0 rounded-full max-sm:hidden ${caseStatusDot(view.status.code)}`}
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
  // The structured case details are secondary: folded until the employer asks for them.
  const [detailsOpen, setDetailsOpen] = useState(false);
  const pill = useRef<HTMLButtonElement>(null);

  const companyId = header.companyId;
  const caseId = view.case.id;
  const step = view.steps.find((item) => item.key === selected) ?? view.steps[0];
  const stepIndex = step ? view.steps.indexOf(step) : -1;
  const nextStep = view.steps
    .slice(stepIndex + 1)
    .find((item) => item.available && item.questions.some((question) => view.missing.includes(question.key)));
  const stage = view.progression?.stages.find((item) => item.status === "in_progress") ?? null;
  // A hold, a caution and the case's jurisdiction are never folded away: the API's own words,
  // above the record (the guided thread they came from isn't shown any more).
  const notices = view.conversation.filter(
    (message) =>
      message.kind === "hold" || message.kind === "caution" || (message.kind === "status_notice" && message.id === "jurisdiction"),
  );

  const choose = (key: string) => {
    setSelected(key);
    requestAnimationFrame(() => document.getElementById("composer-heading")?.focus());
  };

  const closeStatus = useCallback(() => setStatusOpen(false), []);
  // From the case status to a part of the page: the panel closes (focus returns to the case), then the page scrolls.
  const go = useCallback(({ target, step: stepKey }: CaseTarget) => {
    if (stepKey) setSelected(stepKey);
    if (target === "your-answers") setDetailsOpen(true);
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

        <CaseConversationLink canEdit={view.canEdit} companyId={companyId} conversation={askConversation} />

        {notices.length > 0 ? (
          <ul aria-label="Case notices" className="mt-7 flex flex-col gap-6">
            {notices.map((message) => (
              <li key={message.id}>
                <ConversationMessage message={message} />
              </li>
            ))}
          </ul>
        ) : null}

        <section
          aria-labelledby="case-details-heading"
          className="mt-8 scroll-mt-24 rounded-[1.75rem] border border-hero-navy/[0.12] bg-white p-5 shadow-[0_1px_2px_rgb(14_30_61/0.05),0_16px_36px_-24px_rgb(14_30_61/0.4)] sm:p-6"
          id="your-answers"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="flex items-center gap-1.5 text-base font-extrabold text-hero-navy" id="case-details-heading">
                <HelpIcon className="size-4 text-hero-muted" />
                Case details
              </h2>
              <p className="mt-0.5 text-[0.875rem] text-hero-muted">
                {view.missing.length === 0
                  ? "Everything HeroOS asks for is recorded. Review or correct it here."
                  : `${view.missing.length} ${view.missing.length === 1 ? "detail is" : "details are"} still open. Tell HeroOS in your own words, or review them here.`}
              </p>
            </div>
            <button
              aria-controls="case-details-body"
              aria-expanded={detailsOpen}
              className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-hero-border px-4 text-[0.875rem] font-bold text-hero-blue-ink hover:bg-hero-blue-tint/50"
              onClick={() => setDetailsOpen((open) => !open)}
              type="button"
            >
              {detailsOpen ? "Hide case details" : "Review case details"}
              <ChevronDownIcon className={`size-4 transition-transform duration-200 ${detailsOpen ? "rotate-180" : ""}`} />
            </button>
          </div>
          {detailsOpen ? (
            <div id="case-details-body">
              <nav aria-label="Question groups" className="-mx-1 mb-5 mt-5 overflow-x-auto px-1 pb-1">
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
            </div>
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
