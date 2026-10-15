import { StatusBadge } from "@/components/ui/status-badge";
import { JurisdictionStatus } from "@/components/workspace/jurisdiction-status";
import { displayAnswer, PROGRESS_COPY } from "@/lib/workflows/copy";
import type { Question, WorkflowView } from "@/lib/workflows/model";

const sectionHeading = "text-xs font-bold uppercase tracking-[0.14em] text-hero-blue-ink";

/**
 * The Case at a glance: progress (derived by the API from the saved answers
 * and the Company's current jurisdiction readiness), the readiness itself, the
 * known facts as the employer gave them, what is still missing and what this
 * version does not do yet. Nothing here is an assessment.
 */
export function CaseContextPanel({ view }: { view: WorkflowView }) {
  const questions: Question[] = view.steps.flatMap((step) => step.questions);
  const known = questions.filter((question) => view.answers[question.key] !== undefined);
  const missing = questions.filter((question) => view.missing.includes(question.key));

  return (
    <div className="flex flex-col gap-7">
      <section aria-labelledby="progress-heading">
        <h2 className={sectionHeading} id="progress-heading">
          Case progress
        </h2>
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
      </section>

      <section aria-labelledby="jurisdiction-heading">
        <h2 className={sectionHeading} id="jurisdiction-heading">
          Jurisdiction
        </h2>
        <div className="mt-3">
          <JurisdictionStatus jurisdiction={view.jurisdiction} />
        </div>
        {!view.jurisdiction.guidanceAllowed ? (
          <p className="mt-2 text-sm leading-relaxed text-hero-muted">
            Jurisdiction-dependent steps can&apos;t proceed until your company&apos;s jurisdiction is confirmed.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="facts-heading">
        <h2 className={sectionHeading} id="facts-heading">
          Known facts
        </h2>
        {known.length === 0 ? (
          <p className="mt-3 text-[0.9375rem] text-hero-muted">No answers saved yet.</p>
        ) : (
          <dl className="mt-3 flex flex-col gap-3">
            {known.map((question) => (
              <div key={question.key}>
                <dt className="text-sm font-bold text-hero-navy">{question.label}</dt>
                <dd className="mt-0.5 line-clamp-6 whitespace-pre-wrap break-words text-[0.9375rem] leading-relaxed text-hero-navy/85">
                  {displayAnswer(question, view.answers[question.key])}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section aria-labelledby="missing-heading">
        <h2 className={sectionHeading} id="missing-heading">
          Missing information
        </h2>
        {missing.length === 0 ? (
          <p className="mt-3 text-[0.9375rem] text-hero-muted">All initial questions are answered.</p>
        ) : (
          <ul className="mt-3 flex list-disc flex-col gap-1 pl-5 text-[0.9375rem] text-hero-navy">
            {missing.map((question) => (
              <li key={question.key}>{question.label}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="later-heading">
        <h2 className={sectionHeading} id="later-heading">
          Not available yet
        </h2>
        <ul className="mt-3 flex flex-col gap-2">
          {view.notAvailable.map((stage) => (
            <li className="flex items-center justify-between gap-3 text-[0.9375rem] text-hero-navy" key={stage}>
              <span className="min-w-0">{stage}</span>
              <StatusBadge tone="muted">Coming later</StatusBadge>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm leading-relaxed text-hero-muted">
          Nothing in this case has been assessed or decided. HeroOS only records your answers for now.
        </p>
      </section>
    </div>
  );
}
