import type { ReactNode } from "react";

import {
  ChecklistIcon,
  ChevronRightIcon,
  ClockIcon,
  DocumentIcon,
  ShieldIcon,
} from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { caseStatusTone, formatDayTime } from "@/lib/workflows/copy";
import type { WorkflowView } from "@/lib/workflows/model";

/**
 * The case at a glance beside the conversation (top of "Case details"): the
 * official status, the stage in progress, the next step the guided workflow
 * offers and a few recorded facts, with ways into the guided workflow's
 * sections. Every word is the API's or fixed copy about the API's data: never
 * the AI conversation, never an assessment.
 */

/** Where in the guided workflow to go (an element id), and which question group to open. */
export type WorkflowTarget = { target: string; step?: string };

type Next = WorkflowTarget & { title: string; detail: string | null };

/** The next official step, in the guided workflow's order: a hold, then intake answers, then progression. */
function nextOfficialStep(view: WorkflowView): Next | null {
  const hold = view.intake.hold;
  if (hold) return { title: hold.title, detail: hold.body, target: "guided-conversation" };
  const open = view.steps.find(
    (step) => step.available && step.questions.some((question) => view.missing.includes(question.key)),
  );
  if (view.canEdit && open) {
    const left = open.questions.filter((question) => view.missing.includes(question.key)).length;
    return {
      title: `Answer “${open.title}”`,
      detail: `${left} ${left === 1 ? "question" : "questions"} still to answer in the guided workflow.`,
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

const cardClass = "rounded-2xl border border-hero-border bg-white shadow-hero-card";

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 py-1.5">
      <dt className="text-sm text-hero-muted">{term}</dt>
      <dd className="min-w-0 break-words text-sm font-semibold text-hero-navy">{children}</dd>
    </div>
  );
}

function LinkRow({ icon, label, onClick }: { icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <li className="border-t border-hero-border first:border-t-0">
      <button
        className="flex min-h-12 w-full items-center gap-3 px-4 text-left text-[0.9375rem] font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint/60"
        onClick={onClick}
        type="button"
      >
        <span className="text-hero-blue-ink">{icon}</span>
        <span className="min-w-0 flex-1">{label}</span>
        <ChevronRightIcon className="size-4 shrink-0 text-hero-blue-ink" />
      </button>
    </li>
  );
}

export function CaseSummaryPanel({
  view,
  onOpenWorkflow,
}: {
  view: WorkflowView;
  onOpenWorkflow: (where: WorkflowTarget) => void;
}) {
  const stage = view.progression?.stages.find((item) => item.status === "in_progress") ?? null;
  const next = nextOfficialStep(view);
  const total = view.asked.length;
  const answered = total - view.missing.length;
  const pathway = view.progression?.pathway ?? null;
  const escalated = (view.progression?.escalations.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby="case-status-heading" className={`${cardClass} p-4`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-extrabold tracking-[-0.01em] text-hero-navy" id="case-status-heading">
            Case status
          </h2>
          <StatusBadge tone={caseStatusTone(view.status.code)}>{view.status.label}</StatusBadge>
        </div>
        {stage ? (
          <div className="mt-3 flex gap-3 rounded-xl border border-[#f1df8d] bg-hero-yellow-tint p-3">
            <span
              aria-hidden="true"
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-hero-yellow text-hero-navy"
            >
              <DocumentIcon className="size-5" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-bold text-hero-navy/75">Current stage</p>
              <p className="font-extrabold leading-snug text-hero-navy">{stage.title}</p>
              {stage.summary ? <p className="mt-0.5 text-sm leading-relaxed text-hero-navy/80">{stage.summary}</p> : null}
            </div>
          </div>
        ) : null}
        {next ? (
          <div className="mt-3 flex gap-3 rounded-xl border border-hero-border p-3">
            <span
              aria-hidden="true"
              className={`inline-flex size-9 shrink-0 items-center justify-center rounded-full text-white ${
                view.intake.hold ? "bg-hero-danger" : "bg-hero-blue"
              }`}
            >
              {view.intake.hold ? <ShieldIcon className="size-5" /> : <ChecklistIcon className="size-5" />}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-bold text-hero-muted">Next step in the guided workflow</p>
              <p className="font-extrabold leading-snug text-hero-blue-ink">{next.title}</p>
              {next.detail ? (
                <p className="mt-0.5 line-clamp-4 text-sm leading-relaxed text-hero-navy/80">{next.detail}</p>
              ) : null}
              <button
                className="mt-1 inline-flex min-h-9 items-center gap-1 text-left text-sm font-bold text-hero-blue-ink underline-offset-4 hover:underline"
                onClick={() => onOpenWorkflow(next)}
                type="button"
              >
                Open in the guided workflow
                <ChevronRightIcon className="size-4" />
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section aria-labelledby="case-info-heading" className={cardClass}>
        <h2 className="px-4 pt-4 text-base font-extrabold tracking-[-0.01em] text-hero-navy" id="case-info-heading">
          Case info
        </h2>
        <dl className="px-4 pb-3 pt-2">
          <Row term="Case type">{view.workflow.title}</Row>
          <Row term="Created">
            <time dateTime={view.case.createdAt}>{formatDayTime(view.case.createdAt)}</time>
          </Row>
          <Row term="Last updated">
            <time dateTime={view.case.updatedAt}>{formatDayTime(view.case.updatedAt)}</time>
          </Row>
          <Row term="Intake">
            {answered} of {total} questions answered
          </Row>
          {pathway ? (
            <Row term="Pathway">
              {pathway.label}
              <span className="block text-xs font-normal text-hero-muted">
                Recorded by {pathway.byViewer ? "you" : "another administrator"}
              </span>
            </Row>
          ) : null}
          {escalated ? <Row term="Specialist review">Needed before some steps</Row> : null}
        </dl>
        <ul className="border-t border-hero-border">
          <LinkRow
            icon={<ChecklistIcon className="size-5" />}
            label="Next steps"
            onClick={() => onOpenWorkflow({ target: "next-steps" })}
          />
          {view.decisions && view.timeline ? (
            <LinkRow
              icon={<ClockIcon className="size-5" />}
              label="Case history"
              onClick={() => onOpenWorkflow({ target: "case-history" })}
            />
          ) : null}
          {view.decisions ? (
            <LinkRow
              icon={<ShieldIcon className="size-5" />}
              label="Decisions & records"
              onClick={() => onOpenWorkflow({ target: "decisions-history" })}
            />
          ) : null}
          {view.canEdit ? (
            <LinkRow
              icon={<DocumentIcon className="size-5" />}
              label="Documents"
              onClick={() => onOpenWorkflow({ target: "documents" })}
            />
          ) : null}
        </ul>
      </section>
    </div>
  );
}
