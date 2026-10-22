"use client";

import { type ReactNode, useEffect, useState } from "react";

import { CASE_REQUEST_FAILURES, type CaseRequest, type CaseRequestFailure, useCaseRequest } from "@/components/cases/use-case-request";
import { buttonPrimary, buttonSecondary } from "@/components/ui/styles";
import { isWorkflowView, type Question, type WorkflowView } from "@/lib/workflows/model";
import type { ChecklistQuestion, PathwayOption, ProgressMessage, ProgressTransition } from "@/lib/workflows/progression";

import { AdviserTurn, type Outcome as Tone } from "./response-tone";

/**
 * The Case's own formal steps, inside the Ask HeroOS conversation (M2-NEW-08).
 *
 * The Case is one continuous conversation; the workflow engine stays behind
 * it. Ordinary facts come from the conversation itself (HeroOS asks about
 * what the case record still needs, in its own words): while any is open,
 * nothing here asks for it or sends the founder to a form. What only the
 * employer can do (choose the pathway, start or complete a stage, answer a
 * stage's checklist, acknowledge a caution) and the few answers the
 * conversation never collects (whether the company's jurisdiction applies to
 * this employee; the safety screening) appear here as inline HeroOS steps, one
 * at a time, from the Case's view as the API has it now. Every button calls
 * the Case's existing routes (the same as the Case page's), and the API
 * decides: nothing is offered that it wouldn't accept, and nothing is
 * computed here. The AI never presses one: a step only happens when the
 * founder does.
 *
 * Everything else about the Case (every answer, the stages, the decisions,
 * the history) stays in "Review case details", the Case page.
 */

const JURISDICTION_QUESTION = "jurisdiction.case_confirmation";
// A pathway choice: its label and the neutral description, left-aligned (a full-width card button).
const choiceButton =
  "flex w-full flex-col items-start gap-0.5 rounded-2xl border border-hero-control bg-white px-4 py-3 text-left text-base font-bold text-hero-navy transition-colors duration-200 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue";
const READ = { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin", redirect: "error" } as const;

export type CaseStep =
  | { kind: "hold"; title: string; body: string }
  | { kind: "question"; stepKey: string; question: Question }
  | { kind: "gate"; title: string; body: string }
  | { kind: "pathway"; options: PathwayOption[] }
  | { kind: "checklist"; stepKey: string; stage: string; question: ChecklistQuestion }
  | { kind: "transition"; transition: ProgressTransition }
  | { kind: "refused"; transition: ProgressTransition };

/** The one next thing the employer can do in the Case, or null (nothing for them now). */
export function nextCaseStep(view: WorkflowView): CaseStep | null {
  if (!view.canEdit) return null;
  const hold = view.intake.hold;
  if (hold) return { kind: "hold", title: hold.title, body: hold.body };
  const open = view.steps.flatMap((step) =>
    step.available ? step.questions.filter((q) => view.missing.includes(q.key)).map((question) => ({ step, question })) : [],
  );
  // The conversation never collects these: ask them here, one at a time, with their options.
  const structured = open.find(
    ({ step, question }) => question.kind === "choice" && (question.key === JURISDICTION_QUESTION || step.sensitive),
  );
  if (structured) return { kind: "question", stepKey: structured.step.key, question: structured.question };
  // The conversation collects the rest: nothing to press yet.
  if (open.length > 0) return null;
  const progression = view.progression;
  if (progression === null || progression.status.code === "unavailable") return null;
  if (progression.gate) return { kind: "gate", title: progression.gate.title, body: progression.gate.body };
  if (progression.pathway === null) {
    const options = progression.pathwayOptions.filter((option) => option.transition !== null);
    if (options.length > 0) return { kind: "pathway", options };
  }
  const checklist = progression.checklist;
  const unanswered = checklist?.questions.find((q) => view.answers[q.key] === undefined);
  if (checklist && unanswered) {
    return { kind: "checklist", stepKey: checklist.stepKey, stage: checklist.title, question: unanswered };
  }
  const allowed = progression.actions.find((action) => action.allowed);
  if (allowed) return { kind: "transition", transition: allowed };
  const refused = progression.actions.find((action) => !action.allowed);
  return refused ? { kind: "refused", transition: refused } : null;
}

/** What the employer just recorded, in words (from the API's own result). */
function recorded(view: WorkflowView): { tone: Tone; text: string } | null {
  const attempt = view.progression?.attempt ?? null;
  if (attempt === null) return null;
  if (attempt.outcome === "rejected") return { tone: attempt.decision === "escalate" ? "expert" : "block", text: `${attempt.title}. ${attempt.body}` };
  const [kind, target] = attempt.label.split(": ", 2);
  if (attempt.transition.startsWith("pathway:")) {
    return {
      tone: "guidance",
      text: `Recorded: ${view.progression?.pathway?.label ?? target} is your company's decision for this case. HeroOS didn't classify the conduct.`,
    };
  }
  return { tone: "guidance", text: kind === "Start" ? `Started: ${target}.` : `Completed: ${target}.` };
}

function Messages({ items }: { items: ProgressMessage[] }) {
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.code}>
          <span className="font-bold">{item.title}</span>
          {item.body ? <span className="block text-[0.9375rem]">{item.body}</span> : null}
          {item.provisional ? <span className="block text-sm text-hero-muted">A practical caution: its legal basis isn&apos;t confirmed.</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function CaseSteps({
  companyId,
  caseId,
  revision,
  onChanged,
  onAsk,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  /** Changes whenever the Case may have changed (a new turn, a saved note): it is read again. */
  revision: number;
  /** The employer changed the Case here (the conversation's status may read differently now). */
  onChanged?: () => void;
  /** Words to put in the founder's box (never sent by themselves), e.g. "I'm not sure". */
  onAsk?: (words: string) => void;
  fetcher?: typeof fetch;
}) {
  const [view, setView] = useState<WorkflowView | null>(null);
  const [failure, setFailure] = useState<CaseRequestFailure | null>(null);
  const [done, setDone] = useState<{ tone: Tone; text: string } | null>(null);
  // The pathway chosen while its cautions are shown, and the cautions acknowledged.
  const [chosen, setChosen] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState<string | null>(null);
  const { busy, send } = useCaseRequest({ companyId, caseId, fetcher });

  useEffect(() => {
    let cancelled = false;
    async function read() {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/workflow`,
        { ...READ, signal: AbortSignal.timeout(30_000) },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (!cancelled && response.status === 200 && body && isWorkflowView(body.view, caseId)) setView(body.view);
    }
    read().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [caseId, companyId, fetcher, revision]);

  if (view === null) return null;
  const step = nextCaseStep(view);
  const caseHref = `/workspaces/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}`;

  async function act(request: CaseRequest) {
    if (busy || view === null) return;
    setFailure(null);
    const result = await send(view.workflow.revision, request);
    if ("failure" in result) {
      setFailure(result.failure);
      return;
    }
    setView(result.view);
    setDone(request.route === "answers" ? null : recorded(result.view));
    setChosen(null);
    setAcknowledged(null);
    onChanged?.();
  }

  const details = (
    <a className="text-[0.875rem] font-bold text-hero-blue-ink underline underline-offset-2" href={caseHref}>
      Review case details
    </a>
  );
  const optionButtons = (choices: { value: string; label: string }[], onChoose: (value: string) => void, label: string) => (
    <div aria-label={label} className="flex flex-wrap gap-2" role="group">
      {choices.map((choice) => (
        <button className={buttonSecondary} disabled={busy} key={choice.value} onClick={() => onChoose(choice.value)} type="button">
          {choice.label}
        </button>
      ))}
    </div>
  );

  let card: { tone: Tone; title?: string; body: ReactNode } | null = null;
  if (step?.kind === "hold") {
    card = {
      tone: "expert",
      title: step.title,
      body: (
        <>
          <p>{step.body}</p>
          <p>{details}</p>
        </>
      ),
    };
  } else if (step?.kind === "question") {
    card = {
      tone: "guidance",
      body: (
        <>
          <p>For the case record, HeroOS needs your answer:</p>
          <p className="font-bold">{step.question.prompt}</p>
          {optionButtons(
            step.question.options,
            (value) => void act({ route: "answers", stepKey: step.stepKey, answers: { [step.question.key]: value } }),
            step.question.label,
          )}
        </>
      ),
    };
  } else if (step?.kind === "gate") {
    card = {
      tone: "block",
      title: step.title,
      body: (
        <>
          <p>{step.body}</p>
          <p>{details}</p>
        </>
      ),
    };
  } else if (step?.kind === "pathway") {
    const option = step.options.find((item) => item.key === chosen) ?? null;
    const cautions = option?.transition?.warnings ?? [];
    card = {
      tone: option && cautions.length > 0 ? "warning" : "guidance",
      body: (
        <>
          <p>
            Your company now needs to choose the pathway for this case. It&apos;s your decision as the employer: HeroOS
            doesn&apos;t classify the conduct, and you can change it later.
          </p>
          {option && cautions.length > 0 ? (
            <>
              <Messages items={cautions} />
              <div className="flex flex-wrap gap-2">
                <button
                  className={buttonPrimary}
                  disabled={busy}
                  onClick={() => void act({ route: "pathway", pathway: option.key, acknowledgedWarnings: option.transition!.acknowledge })}
                  type="button"
                >
                  I understand: record {option.label}
                </button>
                <button className={buttonSecondary} disabled={busy} onClick={() => setChosen(null)} type="button">
                  Choose again
                </button>
              </div>
            </>
          ) : (
            <div aria-label="Your pathway decision" className="flex flex-col gap-2" role="group">
              {step.options.map((item) => (
                <button
                  className={choiceButton}
                  disabled={busy || !item.transition?.allowed}
                  key={item.key}
                  onClick={() =>
                    item.transition && item.transition.acknowledge.length > 0
                      ? setChosen(item.key)
                      : void act({ route: "pathway", pathway: item.key, acknowledgedWarnings: [] })
                  }
                  type="button"
                >
                  <span>{item.label}</span>
                  <span className="text-sm font-normal text-hero-navy/80">{item.description}</span>
                </button>
              ))}
              {onAsk ? (
                <button
                  className={choiceButton}
                  disabled={busy}
                  onClick={() => onAsk("I'm not sure which pathway fits this case. Can you help me think it through?")}
                  type="button"
                >
                  <span>I&apos;m not sure</span>
                  <span className="text-sm font-normal text-hero-navy/80">Talk it through with HeroOS first. Nothing is recorded.</span>
                </button>
              ) : null}
            </div>
          )}
        </>
      ),
    };
  } else if (step?.kind === "checklist") {
    card = {
      tone: "guidance",
      body: (
        <>
          <p>{step.stage} needs your answer before it can be marked complete:</p>
          <p className="font-bold">{step.question.prompt}</p>
          {step.question.help ? <p className="text-[0.9375rem] text-hero-muted">{step.question.help}</p> : null}
          {optionButtons(
            step.question.options,
            (value) => void act({ route: "answers", stepKey: step.stepKey, answers: { [step.question.key]: value } }),
            step.question.label,
          )}
        </>
      ),
    };
  } else if (step?.kind === "transition") {
    const transition = step.transition;
    const needsAck = transition.acknowledge.length > 0 && acknowledged !== transition.key;
    card = {
      tone: transition.warnings.length > 0 ? "warning" : "guidance",
      body: (
        <>
          <p>
            {transition.kind === "start"
              ? `The next step in your case is ${transition.label.replace(/^Start: /, "")}.`
              : `${transition.label.replace(/^Mark complete: /, "")} has what it needs to be marked complete.`}
          </p>
          {transition.warnings.length > 0 ? <Messages items={transition.warnings} /> : null}
          {needsAck ? (
            <button className={buttonSecondary} disabled={busy} onClick={() => setAcknowledged(transition.key)} type="button">
              I understand
            </button>
          ) : (
            <button
              className={buttonPrimary}
              disabled={busy}
              onClick={() => void act({ route: "transitions", transition: transition.key, acknowledgedWarnings: transition.acknowledge })}
              type="button"
            >
              {transition.kind === "start" ? transition.label.replace(/^Start: /, "Start ") : transition.label.replace(/^Mark complete: /, "Mark complete: ")}
            </button>
          )}
        </>
      ),
    };
  } else if (step?.kind === "refused") {
    const transition = step.transition;
    card = {
      tone: transition.decision === "escalate" ? "expert" : "block",
      title: transition.decision === "escalate" ? `Specialist review needed: ${transition.label}` : `Not yet: ${transition.label}`,
      body: (
        <>
          <Messages items={transition.reasons} />
          {transition.missing.length > 0 ? <p>Still needed: {transition.missing.join("; ")}.</p> : null}
          <p>{details}</p>
        </>
      ),
    };
  }

  if (card === null && done === null && failure === null) return null;
  return (
    <section aria-label="Your case's next step" className="flex flex-col gap-4">
      {done ? (
        <p className="rounded-2xl border border-hero-border bg-white px-4 py-3 text-[0.9375rem] text-hero-navy" role="status">
          {done.text}
        </p>
      ) : null}
      {failure ? (
        <p className="rounded-2xl border border-hero-border bg-white px-4 py-3 text-[0.9375rem] text-hero-navy" role="alert">
          <span className="font-bold">{CASE_REQUEST_FAILURES[failure].title}.</span> {CASE_REQUEST_FAILURES[failure].body}
        </p>
      ) : null}
      {card ? (
        <AdviserTurn id={`case-${caseId}`} outcome={card.tone} title={card.title}>
          <div className="space-y-3">{card.body}</div>
        </AdviserTurn>
      ) : null}
    </section>
  );
}
