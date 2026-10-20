import type { ReactNode } from "react";

import { CheckIcon, ClockIcon, ShieldIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { JurisdictionStatus } from "@/components/workspace/jurisdiction-status";
import { formatDayTime, PROGRESS_COPY } from "@/lib/workflows/copy";
import type { CaseJurisdictionStatus, HistoryItem, Question, WorkflowView } from "@/lib/workflows/model";
import type { ProgressHistoryItem, ProgressHistoryKind } from "@/lib/workflows/progression";

import { CautionCard, HoldCard } from "./conversation";

const sectionHeading = "text-xs font-bold uppercase tracking-[0.14em] text-hero-blue-ink";

const SCREENING_NOW: Record<string, string> = {
  not_applicable: "not available",
  disabled: "not enabled in this environment",
  not_started: "not started",
  incomplete: "not finished",
  not_cleared: "not cleared (“Not sure” answers)",
  cleared: "every answer No",
  positive: "a high-risk factor reported",
};

export const CASE_JURISDICTION: Record<CaseJurisdictionStatus, { status: string; tone: "positive" | "caution" | "muted" }> = {
  resolved: { status: "Confirmed for this case", tone: "positive" },
  awaiting_case_confirmation: { status: "Confirm for this case", tone: "caution" },
  company_unconfirmed: { status: "Waiting for your company's jurisdiction", tone: "muted" },
  company_unsupported: { status: "Not supported yet", tone: "caution" },
  case_not_sure: { status: "Not sure", tone: "caution" },
  case_different: { status: "A different jurisdiction applies", tone: "caution" },
  case_confirmation_outdated: { status: "Confirm again", tone: "caution" },
};

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <h2 className={sectionHeading} id={id}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function QuestionList({ questions, empty }: { questions: Question[]; empty: string }) {
  if (questions.length === 0) return <p className="mt-3 text-[0.9375rem] text-hero-muted">{empty}</p>;
  return (
    <ul className="mt-3 flex list-disc flex-col gap-1 pl-5 text-[0.9375rem] text-hero-navy">
      {questions.map((question) => (
        <li key={question.key}>{question.label}</li>
      ))}
    </ul>
  );
}

type Marker = "alert" | "done" | "event";

function historyMarker(kind: HistoryItem["kind"] | ProgressHistoryKind): Marker {
  switch (kind) {
    case "hold_placed":
    case "hold_kept":
    case "transition_rejected":
    case "escalation_recorded":
      return "alert";
    case "intake_recorded":
    case "hold_lifted":
    case "stage_completed":
      return "done";
    default:
      return "event";
  }
}

function HistoryEntry({ item }: { item: HistoryItem | ProgressHistoryItem }) {
  const kind = historyMarker(item.kind);
  const marker =
    kind === "alert" ? (
      <ShieldIcon className="size-4 text-hero-danger" />
    ) : kind === "done" ? (
      <CheckIcon className="size-4 text-hero-success" />
    ) : (
      <ClockIcon className="size-4 text-hero-blue-ink" />
    );
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      <span aria-hidden="true" className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full border border-hero-border bg-white">
        {marker}
      </span>
      <div className="min-w-0">
        <p className="text-[0.9375rem] font-semibold leading-snug text-hero-navy">{item.title}</p>
        {item.detail ? <p className="mt-0.5 text-sm leading-relaxed text-hero-navy/80">{item.detail}</p> : null}
        <p className="mt-0.5 text-xs text-hero-muted">
          <time dateTime={item.at}>{formatDayTime(item.at)}</time>
          {item.byViewer === true ? " · You" : item.byViewer === false ? " · Another administrator" : ""}
        </p>
      </div>
    </li>
  );
}

/**
 * What must never be folded away: the Case's hold (with when it was first
 * placed and what the current screening says) and HeroOS's cautions, from the
 * API's intake evaluation. Renders nothing when there are neither.
 */
export function CaseAlertsPanel({ view }: { view: WorkflowView }) {
  const { hold, cautions } = view.intake;
  if (!hold && cautions.length === 0) return null;
  return (
    <div className="flex flex-col gap-5">
      {hold ? (
        <Section id="hold-heading" title="Hold">
          <div
            className={`mt-3 rounded-2xl border px-4 py-3.5 text-hero-navy ${
              hold.action === "escalate" ? "border-[#e9b4c0] bg-hero-danger-tint" : "border-[#f1df8d] bg-hero-yellow-tint"
            }`}
          >
            <HoldCard hold={hold} />
          </div>
          {view.intake.escalation ? (
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-hero-navy">
              <dt className="font-bold">Held since</dt>
              <dd>
                <time dateTime={view.intake.escalation.since}>{formatDayTime(view.intake.escalation.since)}</time>
              </dd>
              <dt className="font-bold">Current screening</dt>
              <dd>{SCREENING_NOW[view.intake.screening] ?? view.intake.screening}</dd>
            </dl>
          ) : null}
        </Section>
      ) : null}

      {cautions.length > 0 ? (
        <Section id="cautions-heading" title="Cautions">
          <ul className="mt-3 flex flex-col gap-3">
            {cautions.map((caution) => (
              <li className="rounded-2xl border border-[#f1df8d] bg-hero-yellow-tint px-4 py-3.5 text-hero-navy" key={caution.id}>
                <CautionCard caution={caution} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

/**
 * The rest of the Case's details: progress, the Case's jurisdiction and its
 * basis, the facts as the employer gave them, what is missing or uncertain,
 * where the case history is (M2-04: under "Decisions & history"; before it,
 * the per-source histories here) and what this version doesn't do yet. The
 * hold and cautions are `CaseAlertsPanel`'s. Nothing here is an assessment.
 */
export function CaseContextPanel({ view }: { view: WorkflowView }) {
  const questions: Question[] = view.steps.flatMap((step) => step.questions);
  const asked = questions.filter((question) => view.asked.includes(question.key));
  const known = asked.filter((question) => view.answers[question.key] !== undefined);
  const missing = asked.filter((question) => view.missing.includes(question.key));
  const uncertain = asked.filter((question) => view.uncertain.includes(question.key));
  const { caseJurisdiction } = view.intake;

  return (
    <div className="flex flex-col gap-7">
      <Section id="progress-heading" title="Case progress">
        <ol className="mt-3 flex flex-col">
          {view.progress.map((item) => {
            const copy = PROGRESS_COPY[item.status];
            return (
              <li
                className="flex items-start justify-between gap-3 border-b border-hero-border py-2.5 last:border-b-0"
                key={item.key}
              >
                <span className="min-w-0">
                  <span className="block text-[0.9375rem] font-semibold text-hero-navy">{item.label}</span>
                  <span className="block text-sm text-hero-muted">{item.detail}</span>
                </span>
                <StatusBadge tone={copy.tone}>{copy.label}</StatusBadge>
              </li>
            );
          })}
        </ol>
      </Section>

      {/* The Case's jurisdiction and its status are in "Case info" above; this is their basis. */}
      <Section id="jurisdiction-heading" title="Jurisdiction">
        <p className="mt-3 text-sm leading-relaxed text-hero-navy/80">
          {caseJurisdiction.status === "resolved"
            ? "Based on your company's confirmed jurisdiction and your confirmation for this case."
            : "Checks that depend on the jurisdiction don't run until it's confirmed for this case."}
        </p>
        <div className="mt-3">
          <JurisdictionStatus jurisdiction={view.jurisdiction} />
        </div>
      </Section>

      <Section id="facts-heading" title="Known facts">
        {known.length === 0 ? (
          <p className="mt-3 text-[0.9375rem] text-hero-muted">No answers saved yet.</p>
        ) : (
          <dl className="mt-3 flex flex-col gap-3">
            {known.map((question) => (
              <div key={question.key}>
                <dt className="text-sm font-bold text-hero-navy">{question.label}</dt>
                <dd className="mt-0.5 line-clamp-6 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed text-hero-navy/85">
                  {view.answerLabels[question.key] ?? view.answers[question.key]}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </Section>

      <Section id="missing-heading" title="Missing information">
        <QuestionList empty="Nothing is missing for the questions HeroOS can ask now." questions={missing} />
      </Section>

      {uncertain.length > 0 ? (
        <Section id="uncertain-heading" title="Answers marked “Not sure”">
          <QuestionList empty="" questions={uncertain} />
          <p className="mt-2 text-sm leading-relaxed text-hero-muted">HeroOS never reads “Not sure” as “No”.</p>
        </Section>
      ) : null}

      {view.timeline ? (
        // M2-04: one unified history, with the employer's records, under "Decisions & history".
        <Section id="history-pointer-heading" title="History">
          <p className="mt-3 text-[0.9375rem] leading-relaxed text-hero-navy">
            Everything that happened to this case, with your company&apos;s records, is in one place.{" "}
            <a className="font-bold text-hero-blue-ink underline" href="#case-history">
              See the case history
            </a>
          </p>
        </Section>
      ) : (
        <>
          {/* An API without the unified history (before M2-04): the per-source lists. */}
          <Section id="history-heading" title="Case history">
            <ol className="mt-3 flex flex-col">
              {[...view.history].reverse().map((item) => (
                <HistoryEntry item={item} key={item.id} />
              ))}
            </ol>
          </Section>

          {view.progression && view.progression.history.length > 0 ? (
            <Section id="progression-history-heading" title="Progression history">
              <ol className="mt-3 flex flex-col">
                {[...view.progression.history].reverse().map((item) => (
                  <HistoryEntry item={item} key={item.id} />
                ))}
              </ol>
            </Section>
          ) : null}
        </>
      )}

      <Section id="later-heading" title="Not available yet">
        <ul className="mt-3 flex flex-col gap-2">
          {view.notAvailable.map((stage) => (
            <li className="flex items-center justify-between gap-3 text-[0.9375rem] text-hero-navy" key={stage}>
              <span className="min-w-0">{stage}</span>
              <StatusBadge tone="muted">Coming later</StatusBadge>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm leading-relaxed text-hero-muted">
          Nothing in this case has been assessed or decided. HeroOS records your answers and runs fixed checks on them;
          the checks are development content, not legal advice.
        </p>
      </Section>
    </div>
  );
}
