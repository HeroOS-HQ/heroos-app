"use client";

import { type RefObject, useRef } from "react";

import { OutcomeLabel } from "@/components/ask/response-tone";
import { useModalPanel } from "@/components/app/use-modal-panel";
import { iconButton } from "@/components/app/workspace-chrome";
import { ArrowRightIcon, CheckIcon, ChevronDownIcon, CloseIcon } from "@/components/site/icons";
import type { TimelineEntry } from "@/lib/workflows/decisions";
import { caseStatusDot, formatDay, formatDayTime } from "@/lib/workflows/copy";
import type { WorkflowView } from "@/lib/workflows/model";

import { CASE_JURISDICTION, CaseContextPanel, SCREENING_NOW } from "./case-context-panel";
import { CautionCard, HoldCard } from "./conversation";

/**
 * Case status (approved design, Page 1): a slide-over from the case's name in
 * the header, a bottom sheet on phones. Everything in it is the API's view of
 * the case: its status, the hold and cautions (never folded away), the next
 * official step, what is done and still needed, the facts the employer gave,
 * the latest history, and the rest folded away. Never the conversation's own
 * reading of anything.
 */

/** Where in the case page to go (an element id), and which question group to open. */
export type CaseTarget = { target: string; step?: string };
type Next = CaseTarget & { title: string; detail: string | null };

/** The next official step, in the guided workflow's order: a hold, then intake answers, then progression. */
export function nextOfficialStep(view: WorkflowView): Next | null {
  const hold = view.intake.hold;
  if (hold) return { title: hold.title, detail: null, target: "guided-conversation" };
  const open = view.steps.find(
    (step) => step.available && step.questions.some((question) => view.missing.includes(question.key)),
  );
  if (view.canEdit && open) {
    const left = open.questions.filter((question) => view.missing.includes(question.key)).length;
    return {
      title: `Answer “${open.title}”`,
      detail: `${left} ${left === 1 ? "question" : "questions"} still to answer.`,
      target: "your-answers",
      step: open.key,
    };
  }
  const progression = view.progression;
  if (progression && progression.status.code !== "unavailable") {
    if (progression.gate) return { title: progression.gate.title, detail: progression.gate.body, target: "next-steps" };
    return { title: progression.status.label, detail: null, target: "next-steps" };
  }
  return null;
}

/** The case's rules and context as HeroOS applied them (never an assessment). */
function contextOf(view: WorkflowView, companyName: string): string[] {
  const { caseJurisdiction } = view.intake;
  const rules = view.progression?.rules ?? null;
  return [
    `Company Blueprint: ${companyName}`,
    `Jurisdiction: ${caseJurisdiction.label ?? CASE_JURISDICTION[caseJurisdiction.status]?.status ?? "not confirmed for this case"}`,
    `Workflow: ${view.workflow.title}`,
    rules === null
      ? "Next-step rules: not installed here"
      : rules.provenance === "synthetic"
        ? "Next-step rules: synthetic test rules"
        : `Next-step rules: version ${rules.version}`,
  ];
}

/** The history marker, by what an entry is (approved design: a check, a tone, the current step). */
function markerOf(entry: TimelineEntry): string {
  if (entry.status === "specialist_review" || entry.status === "on_hold") return "tone-expert bg-(--tone-chip) text-(--tone-ink)";
  if (entry.nature === "refused_request") return "tone-warning bg-(--tone-chip) text-(--tone-ink)";
  if (entry.nature === "employer_record") return "tone-guidance bg-(--tone-chip) text-(--tone-ink)";
  return "bg-hero-navy text-white";
}

const sectionTitle = "text-[0.9375rem] font-extrabold text-hero-navy";
const HISTORY_SHOWN = 6;

export function CaseStatusPanel({
  view,
  companyName,
  onClose,
  onGo,
  returnTo,
}: {
  view: WorkflowView;
  companyName: string;
  onClose: () => void;
  /** Close the panel and go to a part of the case page. */
  onGo: (target: CaseTarget) => void;
  /** The case's name in the header: focus returns there on close. */
  returnTo?: RefObject<HTMLElement | null>;
}) {
  const panel = useRef<HTMLElement>(null);
  useModalPanel(true, onClose, panel, returnTo);

  const stage = view.progression?.stages.find((item) => item.status === "in_progress") ?? null;
  const next = nextOfficialStep(view);
  const done = view.progress.filter((item) => item.status === "completed");
  const needed = view.progress.filter((item) => item.status !== "completed" && item.status !== "coming_later");
  const facts = view.steps
    .flatMap((step) => step.questions)
    .filter((question) => view.asked.includes(question.key) && view.answers[question.key] !== undefined);
  // The latest entries, oldest first (the API sends the newest first).
  const history = [...(view.timeline?.entries ?? []).slice(0, HISTORY_SHOWN)].reverse();
  const { hold, cautions, escalation } = view.intake;

  return (
    <div className="fixed inset-0 z-40">
      <div aria-hidden="true" className="ws-fade absolute inset-0 bg-hero-navy/20" onClick={onClose} />
      <aside
        aria-labelledby="status-title"
        aria-modal="true"
        className="ws-panel-in absolute inset-x-0 bottom-0 max-h-[88%] overflow-y-auto overscroll-contain rounded-t-[1.75rem] bg-white shadow-[0_-20px_60px_-24px_rgb(14_30_61/0.45)] sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[27rem] sm:rounded-none sm:rounded-l-[1.75rem]"
        id="case-status"
        ref={panel}
        // An in-page link inside the panel (e.g. to the case history) closes it and goes there.
        onClickCapture={(event) => {
          const link = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
          const id = link?.getAttribute("href")?.slice(1);
          if (!id) return;
          event.preventDefault();
          onGo({ target: id });
        }}
        role="dialog"
        tabIndex={-1}
      >
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-hero-border bg-white/95 px-6 pb-4 pt-5 backdrop-blur">
          <div className="min-w-0 flex-1">
            <p className="text-[0.75rem] font-bold uppercase tracking-[0.12em] text-hero-muted">Case status</p>
            <h2 className="mt-1 break-words text-[1.25rem] font-extrabold leading-tight tracking-[-0.015em] text-hero-navy" id="status-title">
              {view.case.title}
            </h2>
            <p className="mt-1 text-[0.8125rem] text-hero-muted">
              {view.workflow.title} · Opened <time dateTime={view.case.createdAt}>{formatDay(view.case.createdAt)}</time>
            </p>
          </div>
          <button aria-label="Close case status" className={`${iconButton} -mr-2 -mt-1`} onClick={onClose} type="button">
            <CloseIcon className="size-5" />
          </button>
        </div>

        <div className="space-y-6 px-6 py-5">
          <section aria-labelledby="st-now">
            <h3 className="sr-only" id="st-now">
              Now
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex min-h-7 shrink-0 items-center gap-1.5 rounded-full border border-hero-border bg-white px-2.5 text-[0.8125rem] font-semibold text-hero-navy">
                <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${caseStatusDot(view.status.code)}`} />
                {view.status.label}
              </span>
              {stage ? (
                <p className="text-[0.875rem] text-hero-muted">
                  <span className="font-semibold text-hero-navy">Now:</span> {stage.title}
                </p>
              ) : null}
            </div>
            {view.progression && view.progression.escalations.length > 0 ? (
              <p className="tone-expert mt-2.5 flex flex-wrap items-center gap-2 text-[0.875rem] font-semibold text-(--tone-ink)">
                <OutcomeLabel outcome="expert" />
                Specialist review needed
              </p>
            ) : null}
          </section>

          {hold ? (
            <section aria-labelledby="st-hold" className={`${hold.action === "escalate" ? "tone-expert" : "tone-stop"} rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5 text-hero-navy`}>
              <h3 className="flex items-center gap-2 text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)" id="st-hold">
                <OutcomeLabel outcome={hold.action === "escalate" ? "expert" : "block"} />
                On hold
              </h3>
              <div className="mt-2">
                <HoldCard hold={hold} />
              </div>
              {escalation ? (
                <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                  <dt className="font-bold">Held since</dt>
                  <dd>
                    <time dateTime={escalation.since}>{formatDayTime(escalation.since)}</time>
                  </dd>
                  <dt className="font-bold">Current screening</dt>
                  <dd>{SCREENING_NOW[view.intake.screening] ?? view.intake.screening}</dd>
                </dl>
              ) : null}
            </section>
          ) : null}

          {cautions.length > 0 ? (
            <section aria-labelledby="st-cautions">
              <h3 className={sectionTitle} id="st-cautions">
                Cautions
              </h3>
              <ul className="mt-2 space-y-2.5">
                {cautions.map((caution) => (
                  <li className="tone-warning rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3 text-hero-navy" key={caution.id}>
                    <CautionCard caution={caution} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {next ? (
            <section aria-labelledby="st-next" className="tone-guidance rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5">
              <h3 className="text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)" id="st-next">
                Your next step
              </h3>
              <p className="mt-1 text-[0.9375rem] font-semibold leading-snug text-hero-navy">{next.title}</p>
              {next.detail ? <p className="mt-1 text-[0.875rem] leading-relaxed text-hero-navy/80">{next.detail}</p> : null}
              <button
                className="mt-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg text-[0.875rem] font-bold text-hero-blue-ink underline-offset-4 hover:underline max-sm:min-h-11"
                onClick={() => onGo(next)}
                type="button"
              >
                Take me there
                <ArrowRightIcon className="size-4" />
              </button>
            </section>
          ) : null}

          <div className="grid gap-5">
            {done.length > 0 ? (
              <section aria-labelledby="st-done">
                <h3 className={sectionTitle} id="st-done">
                  Done so far
                </h3>
                <ul className="mt-2 space-y-1.5 text-[0.875rem] text-hero-navy/85">
                  {done.map((item) => (
                    <li className="flex gap-2" key={item.key}>
                      <CheckIcon className="mt-[0.15rem] size-4 shrink-0 text-hero-success" />
                      {item.label}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {needed.length > 0 ? (
              <section aria-labelledby="st-needed">
                <h3 className={sectionTitle} id="st-needed">
                  Still needed
                </h3>
                <ul className="mt-2 space-y-1.5 text-[0.875rem] text-hero-navy/85">
                  {needed.map((item) => (
                    <li className="flex gap-2" key={item.key}>
                      <span aria-hidden="true" className="mt-[0.3rem] size-3 shrink-0 rounded-full border-2 border-hero-control" />
                      <span className="min-w-0">
                        {item.label}
                        {item.detail ? <span className="block text-[0.8125rem] text-hero-muted">{item.detail}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>

          <section aria-labelledby="st-facts">
            <h3 className={sectionTitle} id="st-facts">
              What you&apos;ve told HeroOS
            </h3>
            {facts.length === 0 ? (
              <p className="mt-2 text-[0.875rem] text-hero-muted">Nothing saved yet.</p>
            ) : (
              <dl className="mt-2 divide-y divide-hero-border rounded-2xl border border-hero-border">
                {facts.map((question) => (
                  <div className="grid gap-1 px-4 py-2.5 text-[0.875rem] min-[420px]:grid-cols-[8rem_1fr] min-[420px]:gap-3" key={question.key}>
                    <dt className="text-hero-muted">{question.label}</dt>
                    <dd className="line-clamp-4 whitespace-pre-wrap break-words font-semibold text-hero-navy">
                      {view.answerLabels[question.key] ?? view.answers[question.key]}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>

          {history.length > 0 ? (
            <section aria-labelledby="st-history">
              <h3 className={sectionTitle} id="st-history">
                Case history
              </h3>
              <ol className="relative mt-3 space-y-3 before:absolute before:bottom-2 before:left-[0.5625rem] before:top-2 before:w-px before:bg-hero-border">
                {history.map((entry) => (
                  <li className="relative flex items-start gap-3" key={entry.id}>
                    <span
                      aria-hidden="true"
                      className={`relative z-10 mt-0.5 inline-flex size-[1.125rem] shrink-0 items-center justify-center rounded-full ${markerOf(entry)}`}
                    >
                      <CheckIcon className="size-2.5" />
                    </span>
                    <p className="min-w-0 text-[0.875rem] font-semibold leading-snug text-hero-navy">
                      {entry.title}
                      <time className="ml-2 text-xs font-medium tabular-nums text-hero-muted" dateTime={entry.at}>
                        {formatDayTime(entry.at)}
                      </time>
                    </p>
                  </li>
                ))}
              </ol>
              {(view.timeline?.total ?? 0) > history.length ? (
                <button
                  className="mt-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg text-[0.875rem] font-bold text-hero-blue-ink underline-offset-4 hover:underline max-sm:min-h-11"
                  onClick={() => onGo({ target: "case-history" })}
                  type="button"
                >
                  The whole case history
                  <ArrowRightIcon className="size-4" />
                </button>
              ) : null}
            </section>
          ) : null}

          {/* Context transparency lives here, folded away, never under the question. */}
          <details className="group rounded-2xl border border-hero-border px-4 py-3">
            <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between text-[0.875rem] font-semibold text-hero-navy [&::-webkit-details-marker]:hidden">
              How HeroOS tailored this case
              <ChevronDownIcon className="size-4 text-hero-muted transition-transform duration-200 group-open:rotate-180" />
            </summary>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {contextOf(view, companyName).map((item) => (
                <li className="rounded-full bg-hero-navy/[0.05] px-2.5 py-1 text-[0.8125rem] font-medium text-hero-navy/85" key={item}>
                  {item}
                </li>
              ))}
            </ul>
          </details>

          <details className="group rounded-2xl border border-hero-border" id="case-full-details">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 [&::-webkit-details-marker]:hidden">
              <span className="min-w-0">
                <span className="block text-[0.875rem] font-semibold text-hero-navy">Full case details</span>
                <span className="block text-xs text-hero-muted">Progress, jurisdiction, facts, missing information</span>
              </span>
              <ChevronDownIcon className="size-4 shrink-0 text-hero-muted transition-transform duration-200 group-open:rotate-180" />
            </summary>
            <div className="border-t border-hero-border px-4 pb-4 pt-4">
              <CaseContextPanel view={view} />
            </div>
          </details>
        </div>
      </aside>
    </div>
  );
}
