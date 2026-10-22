"use client";

import { useEffect, useRef, useState } from "react";

import { AlertIcon, CheckIcon, ChecklistIcon, ShieldIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import { formatDayTime, type Tone } from "@/lib/workflows/copy";
import type { WorkflowView } from "@/lib/workflows/model";
import {
  checklistStep,
  type PathwayOption,
  type ProgressMessage,
  type ProgressTransition,
  type StageStatus,
} from "@/lib/workflows/progression";

import { AnswersForm } from "./answers-form";
import { ProvisionalTag } from "./conversation";
import { CASE_REQUEST_FAILURES, type CaseRequestFailure, useCaseRequest } from "./use-case-request";

/**
 * "Next steps": workflow progression (M2-03), rendered from the API's view.
 *
 * The API decides everything: the current position, which transitions exist,
 * whether each would be accepted now and why not. This component offers a
 * button only for a transition the API says it would accept, shows the
 * reasons (and what's missing) for the others, and asks the employer to
 * acknowledge exactly the cautions the API names. Every request carries the
 * revision it was based on and a request key; a retry after a lost response
 * reuses the key, so the API applies it once. A refused request is recorded
 * by the API and nothing moves.
 *
 * The pathway is the employer's own judgement, recorded only by their own
 * click: HeroOS can explain the choices in Ask HeroOS but never chooses one.
 * Ask HeroOS offers the same steps inline (M2-NEW-08); both send the same
 * requests (``useCaseRequest``).
 */

type Outcome = { kind: "attempt" } | { kind: "failed"; reason: CaseRequestFailure } | null;

const FAILURES = CASE_REQUEST_FAILURES;

const STAGE_COPY: Record<StageStatus, { label: string; tone: Tone }> = {
  completed: { label: "Completed", tone: "positive" },
  in_progress: { label: "In progress", tone: "neutral" },
  next: { label: "Next", tone: "caution" },
  later: { label: "Not yet", tone: "muted" },
};

const sectionHeading = "text-base font-extrabold tracking-[-0.01em] text-hero-navy";

function Message({ message }: { message: ProgressMessage }) {
  return (
    <div>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-bold">
        <span>{message.title}</span>
        {message.provisional ? <ProvisionalTag /> : null}
      </p>
      <p className="mt-0.5 text-[0.9375rem] leading-relaxed text-hero-navy/85">{message.body}</p>
    </div>
  );
}

function Refusal({ transition }: { transition: ProgressTransition }) {
  const escalated = transition.decision === "escalate";
  return (
    <Notice title={escalated ? "Can't continue without specialist review" : "Not available yet"} tone={escalated ? "danger" : "caution"}>
      <div className="flex flex-col gap-3">
        {transition.reasons.map((reason) => (
          <Message key={reason.code} message={reason} />
        ))}
        {transition.missing.length > 0 ? (
          <div>
            <p className="font-bold">Still needed</p>
            <ul className="mt-1 list-disc pl-5">
              {transition.missing.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {transition.warnings.length > 0 ? (
          <div className="flex flex-col gap-2 border-t border-hero-border pt-3">
            {transition.warnings.map((warning) => (
              <Message key={warning.code} message={warning} />
            ))}
          </div>
        ) : null}
      </div>
    </Notice>
  );
}

function Acknowledgment({
  id,
  transition,
  checked,
  onChange,
  disabled,
}: {
  id: string;
  transition: ProgressTransition;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled: boolean;
}) {
  if (transition.warnings.length === 0) return null;
  return (
    <Notice title={transition.warnings.length > 1 ? "Cautions" : "Caution"} tone="caution">
      <div className="flex flex-col gap-3">
        {transition.warnings.map((warning) => (
          <Message key={warning.code} message={warning} />
        ))}
        {transition.acknowledge.length > 0 ? (
          <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 font-semibold text-hero-navy" htmlFor={id}>
            <input
              checked={checked}
              className="size-4 accent-hero-blue"
              disabled={disabled}
              id={id}
              onChange={(event) => onChange(event.target.checked)}
              type="checkbox"
            />
            I&apos;ve read {transition.warnings.length > 1 ? "these cautions" : "this caution"}
          </label>
        ) : null}
      </div>
    </Notice>
  );
}

export function ProgressionPanel({
  companyId,
  caseId,
  view,
  onUpdated,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  view: WorkflowView;
  onUpdated: (view: WorkflowView) => void;
  fetcher?: typeof fetch;
}) {
  const progression = view.progression;
  const { busy, send: sendRequest } = useCaseRequest({ companyId, caseId, fetcher });
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [choice, setChoice] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [acknowledged, setAcknowledged] = useState<Record<string, boolean>>({});
  const outcomeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (outcome !== null) outcomeRef.current?.focus();
  }, [outcome]);

  if (progression === null) {
    return (
      <div className="flex flex-col gap-5">
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="next-steps-heading">
          Next steps
        </h2>
        <Notice title="Next steps aren't available" tone="caution">
          This version of HeroOS can&apos;t guide the next stages of the case. Your answers stay saved.
        </Notice>
      </div>
    );
  }

  async function send(route: "pathway" | "transitions", target: { pathway: string } | { transition: string }, warnings: string[]) {
    if (busy) return;
    const result = await sendRequest(
      view.workflow.revision,
      "pathway" in target
        ? { route: "pathway", pathway: target.pathway, acknowledgedWarnings: warnings }
        : { route: "transitions", transition: target.transition, acknowledgedWarnings: warnings },
    );
    if ("failure" in result) {
      setOutcome({ kind: "failed", reason: result.failure });
      return;
    }
    setChoice(null);
    setChanging(false);
    setAcknowledged({});
    onUpdated(result.view);
    setOutcome({ kind: "attempt" });
  }

  const { gate, rules, pathway, stages, actions, checklist, escalations } = progression;
  const offered = progression.pathwayOptions.filter((option) => option.transition !== null);
  const selected = offered.find((option) => option.key === choice) ?? null;
  const selectedTransition = selected?.transition ?? null;
  const showChoice = view.canEdit && gate === null && (pathway === null || changing);
  const attempt = progression.attempt;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy" id="next-steps-heading">
          Next steps
        </h2>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={gate === null ? "neutral" : "caution"}>{progression.status.label}</StatusBadge>
          {/* A recorded escalation blocks that step until a specialist reviews it: say so at the top. */}
          {escalations.length > 0 ? <StatusBadge tone="caution">Specialist review needed</StatusBadge> : null}
        </div>
      </div>

      {rules?.notice ? (
        <Notice title={rules.notice.title} tone="caution">
          {rules.notice.body}
        </Notice>
      ) : null}

      <div aria-live="polite" className="outline-none" ref={outcomeRef} role="status" tabIndex={-1}>
        {outcome?.kind === "failed" ? (
          <Notice title={FAILURES[outcome.reason].title} tone="danger">
            {FAILURES[outcome.reason].body}
            {outcome.reason === "conflict" || outcome.reason === "forbidden" || outcome.reason === "not_found" ? (
              <>
                {" "}
                <button className="font-bold underline" onClick={() => window.location.reload()} type="button">
                  Reload the case
                </button>
              </>
            ) : outcome.reason === "session_expired" ? (
              <>
                {" "}
                <a className="font-bold underline" href="/auth/login">
                  Sign in
                </a>
              </>
            ) : null}
          </Notice>
        ) : outcome?.kind === "attempt" && attempt ? (
          <Notice
            title={attempt.title}
            tone={attempt.outcome === "applied" ? "success" : attempt.decision === "escalate" ? "danger" : "caution"}
          >
            {attempt.body}
          </Notice>
        ) : null}
      </div>

      {gate ? (
        <Notice title={gate.title} tone={gate.code === "case_held" ? "danger" : "caution"}>
          {gate.body}
        </Notice>
      ) : null}

      <section aria-labelledby="pathway-heading" className="rounded-2xl border border-hero-border bg-white p-4 sm:p-5">
        <h3 className={sectionHeading} id="pathway-heading">
          Your pathway decision
        </h3>
        {pathway ? (
          <div className="mt-2">
            <p className="flex flex-wrap items-center gap-2 text-[0.9375rem] text-hero-navy">
              <CheckIcon className="size-4 text-hero-success" />
              <span className="font-bold">{pathway.label}</span>
              <span className="text-hero-muted">(your decision)</span>
            </p>
            <p className="mt-1 text-sm text-hero-muted">
              Recorded <time dateTime={pathway.decidedAt}>{formatDayTime(pathway.decidedAt)}</time>
              {pathway.byViewer ? " by you" : " by another administrator"}
              {pathway.previous ? ` · changed from ${pathway.previous}` : ""}
            </p>
            {view.canEdit && gate === null && !changing && offered.length > 0 ? (
              <button className="mt-2 font-bold text-hero-blue-ink underline" onClick={() => setChanging(true)} type="button">
                Change pathway
              </button>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 text-[0.9375rem] leading-relaxed text-hero-navy/85">
            {gate === null ? "No pathway recorded yet." : "No pathway recorded. Choosing one isn't available right now."}
          </p>
        )}

        {showChoice ? (
          <form
            className="mt-4 flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (selected && selectedTransition?.allowed) {
                void send("pathway", { pathway: selected.key }, selectedTransition.acknowledge);
              }
            }}
          >
            <fieldset>
              <legend className="text-[0.9375rem] leading-relaxed text-hero-navy/85">
                Choose the pathway that matches your own judgement as the employer: it&apos;s your decision. HeroOS can
                explain the choices in Ask HeroOS, but it doesn&apos;t classify the incident, choose a pathway for you or
                validate your choice. You can change it later; earlier records stay in the history.
              </legend>
              <div className="mt-3 flex flex-col gap-2">
                {offered.map((option: PathwayOption) => {
                  const transition = option.transition!;
                  const id = `pathway-${option.key}`;
                  return (
                    <div className="rounded-xl border border-hero-border px-3.5 py-3" key={option.key}>
                      <label className="flex cursor-pointer items-start gap-3 has-[:disabled]:cursor-not-allowed" htmlFor={id}>
                        <input
                          checked={choice === option.key}
                          className="mt-1 size-4 accent-hero-blue"
                          disabled={busy || !transition.allowed}
                          id={id}
                          name="pathway"
                          onChange={() => setChoice(option.key)}
                          type="radio"
                          value={option.key}
                        />
                        <span className="min-w-0">
                          <span className="block font-bold text-hero-navy">{option.label}</span>
                          <span className="block text-sm leading-relaxed text-hero-navy/80">{option.description}</span>
                        </span>
                      </label>
                      {!transition.allowed ? (
                        <div className="mt-2">
                          <Refusal transition={transition} />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </fieldset>
            {selectedTransition ? (
              <Acknowledgment
                checked={acknowledged[selectedTransition.key] ?? false}
                disabled={busy}
                id={`ack-${selectedTransition.key.replace(":", "-")}`}
                onChange={(checked) => setAcknowledged((current) => ({ ...current, [selectedTransition.key]: checked }))}
                transition={selectedTransition}
              />
            ) : null}
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
              {changing ? (
                <button className={buttonSecondary} disabled={busy} onClick={() => setChanging(false)} type="button">
                  Keep my current choice
                </button>
              ) : null}
              <button
                className={buttonPrimary}
                disabled={
                  busy ||
                  !selectedTransition?.allowed ||
                  (selectedTransition.acknowledge.length > 0 && !acknowledged[selectedTransition.key])
                }
                type="submit"
              >
                {busy ? "Recording…" : "Record my decision"}
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {stages.length > 0 ? (
        <section aria-labelledby="stages-heading">
          <h3 className={sectionHeading} id="stages-heading">
            Stages
          </h3>
          <ol className="mt-3 flex flex-col gap-2">
            {stages.map((stage, index) => {
              const copy = STAGE_COPY[stage.status];
              return (
                <li
                  aria-current={stage.status === "in_progress" ? "step" : undefined}
                  className={`flex items-start justify-between gap-3 rounded-xl border px-3.5 py-3 ${
                    stage.status === "in_progress" ? "border-hero-blue bg-hero-blue-tint" : "border-hero-border bg-white"
                  }`}
                  key={stage.key}
                >
                  <span className="min-w-0">
                    <span className="block font-bold text-hero-navy">
                      {index + 1}. {stage.title}
                    </span>
                    <span className="block text-sm leading-relaxed text-hero-navy/80">{stage.summary}</span>
                    {stage.optional || stage.terminal ? (
                      <span className="mt-1 block text-xs font-bold uppercase tracking-[0.12em] text-hero-muted">
                        {[stage.optional ? "Optional" : null, stage.terminal ? "Last stage" : null].filter(Boolean).join(" · ")}
                      </span>
                    ) : null}
                  </span>
                  <StatusBadge tone={copy.tone}>{copy.label}</StatusBadge>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {actions.length > 0 ? (
        <section aria-labelledby="actions-heading">
          <h3 className={sectionHeading} id="actions-heading">
            What you can do next
          </h3>
          <ul className="mt-3 flex flex-col gap-3">
            {actions.map((action) => {
              const needsAck = action.acknowledge.length > 0;
              const ready = action.allowed && (!needsAck || (acknowledged[action.key] ?? false));
              return (
                <li className="flex flex-col gap-3 rounded-2xl border border-hero-border bg-white p-4" key={action.key}>
                  <p className="flex items-center gap-2 font-bold text-hero-navy">
                    {action.allowed ? (
                      <ChecklistIcon className="size-4 text-hero-blue-ink" />
                    ) : action.decision === "escalate" ? (
                      <ShieldIcon className="size-4 text-hero-danger" />
                    ) : (
                      <AlertIcon className="size-4" />
                    )}
                    {action.label}
                  </p>
                  {action.allowed && view.canEdit ? (
                    <>
                      <Acknowledgment
                        checked={acknowledged[action.key] ?? false}
                        disabled={busy}
                        id={`ack-${action.key.replace(":", "-")}`}
                        onChange={(checked) => setAcknowledged((current) => ({ ...current, [action.key]: checked }))}
                        transition={action}
                      />
                      <div className="flex justify-end">
                        <button
                          className={buttonPrimary}
                          disabled={busy || !ready}
                          onClick={() => void send("transitions", { transition: action.key }, action.acknowledge)}
                          type="button"
                        >
                          {busy ? "Recording…" : action.kind === "start" ? "Start this stage" : "Mark this stage complete"}
                        </button>
                      </div>
                    </>
                  ) : action.allowed ? (
                    <p className="text-sm text-hero-muted">Only company administrators can move the case on.</p>
                  ) : (
                    <Refusal transition={action} />
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {checklist && view.canEdit ? (
        <section aria-label="Stage checklist" className="rounded-2xl border border-hero-border bg-white p-4 sm:p-5">
          <AnswersForm
            answers={view.answers}
            caseId={caseId}
            companyId={companyId}
            fetcher={fetcher}
            headingId="checklist-heading"
            key={checklist.stepKey}
            onSaved={onUpdated}
            revision={view.workflow.revision}
            step={checklistStep(checklist)}
            submitLabel="Save checklist"
          />
        </section>
      ) : null}

      {escalations.length > 0 ? (
        <section aria-labelledby="escalations-heading">
          <h3 className={sectionHeading} id="escalations-heading">
            Specialist review needed
          </h3>
          <ul className="mt-3 flex flex-col gap-2">
            {escalations.map((item) => (
              <li className="rounded-xl border border-[#e9b4c0] bg-hero-danger-tint px-3.5 py-3 text-hero-navy" key={item.transition}>
                <p className="font-bold">{item.label}</p>
                <p className="mt-0.5 text-sm">
                  Recorded <time dateTime={item.since}>{formatDayTime(item.since)}</time>. Not resolved: HeroOS
                  doesn&apos;t offer expert review in the app yet and hasn&apos;t contacted anyone.
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="text-sm leading-relaxed text-hero-muted">
        HeroOS checks each step against fixed rules and records what happened. It doesn&apos;t assess the incident,
        decide a penalty or end anyone&apos;s employment. Not available yet: {progression.notAvailable.join(", ").toLowerCase()}.
      </p>
    </div>
  );
}
