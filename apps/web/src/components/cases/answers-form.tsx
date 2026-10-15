"use client";

import { useEffect, useRef, useState } from "react";

import { AlertIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, fieldError, hint as hintClass, input, label as labelClass } from "@/components/ui/styles";
import {
  type AnswerErrors,
  buildAnswers,
  changedCount,
  type Draft,
  draftFrom,
  isAsked,
  isoDay,
  mergedAnswers,
} from "@/lib/workflows/answers";
import { isWorkflowView, NOT_SURE, type Question, type Step, type WorkflowView } from "@/lib/workflows/model";

/**
 * The composer: one step's structured questions (a question group). It sends
 * only changed answers, with the revision they were based on
 * (`expectedRevision`) and a submission key. Retrying the identical change
 * after a lost response reuses the key, so the API applies it once; anything
 * else gets a new key. A stale revision (another window or administrator saved
 * first) is refused by the API and the employer is asked to reload. The API
 * enforces the administrator role and decides which steps can be answered.
 *
 * Follow-up questions appear as soon as the answer they depend on is given in
 * the draft, and are left out (never sent) when it changes away.
 */

type Failure = "session_expired" | "forbidden" | "invalid" | "conflict" | "unavailable" | "not_found";
type Status = { kind: "idle" } | { kind: "saving" } | { kind: "saved" } | { kind: "unchanged" } | { kind: "failed"; reason: Failure };

const FAILURES: Record<Failure, { title: string; body: string }> = {
  session_expired: {
    title: "Your session has ended",
    body: "Your answers weren't saved. Copy anything you don't want to lose, then sign in again.",
  },
  forbidden: {
    title: "Only company administrators can save answers",
    body: "Your access may have changed. Reload the page to see the case as it is now.",
  },
  invalid: { title: "Some answers need attention", body: "HeroOS couldn't accept the highlighted answers." },
  conflict: {
    title: "This case has changed since you opened it",
    body: "Another window or administrator saved answers first, or this step can't be answered right now. Reload the case to see its current state, then make your changes again.",
  },
  not_found: { title: "This case can't be found", body: "It may not be available to you any more. Reload the page." },
  unavailable: {
    title: "Your answers weren't saved",
    body: "HeroOS couldn't be reached. Try again: if the save did go through, it won't be applied twice.",
  },
};

const fieldId = (key: string) => `q-${key.replace(/[^a-z0-9]+/g, "-")}`;

function QuestionField({
  question,
  value,
  error,
  onChange,
  disabled,
}: {
  question: Question;
  value: string;
  error?: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const id = fieldId(question.key);
  const hintId = question.help ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  const hint = question.help ? (
    <span className={hintClass} id={hintId}>
      {question.help}
    </span>
  ) : null;
  const errorText = error ? (
    <p className={fieldError} id={errorId}>
      <AlertIcon className="mt-0.5 size-4 shrink-0" />
      <span>
        <span className="sr-only">Error: </span>
        {error}
      </span>
    </p>
  ) : null;

  if (question.kind === "choice") {
    return (
      <fieldset aria-describedby={describedBy} aria-invalid={error ? true : undefined}>
        <legend className={labelClass}>{question.prompt}</legend>
        {hint}
        <div className="mt-2 flex flex-wrap gap-2">
          {question.options.map((option) => {
            const checked = value === option.value;
            return (
              <label
                className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border px-4 text-[0.9375rem] font-semibold transition-colors duration-150 has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-hero-blue ${
                  checked ? "border-hero-blue bg-hero-blue-tint text-hero-navy" : "border-hero-control bg-white text-hero-navy hover:bg-hero-bg"
                }`}
                key={option.value}
              >
                <input
                  checked={checked}
                  className="size-4 accent-hero-blue"
                  disabled={disabled}
                  id={`${id}-${option.value}`}
                  name={id}
                  onChange={() => onChange(option.value)}
                  type="radio"
                  value={option.value}
                />
                {option.label}
              </label>
            );
          })}
        </div>
        {errorText}
      </fieldset>
    );
  }

  if (question.kind === "date") {
    const notSure = value === NOT_SURE;
    return (
      <div>
        <label className={labelClass} htmlFor={id}>
          {question.prompt}
        </label>
        {hint}
        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center">
          <input
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            className={`${input} mt-0 sm:max-w-[14rem]`}
            disabled={disabled || notSure}
            id={id}
            min="1990-01-01"
            onChange={(event) => onChange(event.target.value)}
            type="date"
            value={notSure ? "" : value}
          />
          {question.allowNotSure ? (
            <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 text-[0.9375rem] font-semibold text-hero-navy">
              <input
                checked={notSure}
                className="size-4 accent-hero-blue"
                disabled={disabled}
                id={`${id}-not-sure`}
                onChange={(event) => onChange(event.target.checked ? NOT_SURE : "")}
                type="checkbox"
              />
              Not sure
            </label>
          ) : null}
        </div>
        {errorText}
      </div>
    );
  }

  const length = value.length;
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        {question.prompt}
      </label>
      {hint}
      <textarea
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        className={`${input} min-h-36 resize-y leading-relaxed`}
        disabled={disabled}
        id={id}
        maxLength={question.maxLength ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        rows={6}
        value={value}
      />
      {question.maxLength !== null ? (
        <p className="mt-1 text-right text-sm text-hero-muted">
          {length.toLocaleString("en-GB")} / {question.maxLength.toLocaleString("en-GB")} characters
        </p>
      ) : null}
      {errorText}
    </div>
  );
}

export function AnswersForm({
  companyId,
  caseId,
  step,
  answers,
  revision,
  onSaved,
  next,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  step: Step;
  answers: Record<string, string>;
  revision: number;
  onSaved: (view: WorkflowView) => void;
  /** The next step with questions left, offered after a save. */
  next?: { title: string; go: () => void } | null;
  fetcher?: typeof fetch;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(step, answers));
  const [errors, setErrors] = useState<AnswerErrors>({});
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const inFlight = useRef(false);
  const submission = useRef<{ signature: string; key: string } | null>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  // Rendering never reads the clock (the server and browser dates can differ);
  // "today" is taken when the employer saves.
  const merged = mergedAnswers(step, draft, answers);
  const visible = step.questions.filter((question) => isAsked(question, merged));
  const missingCount = visible.filter((question) => merged[question.key] === undefined).length;
  const dirty = visible.some((question) => {
    const value = draft[question.key] ?? "";
    return (question.kind === "text" ? value.trim() : value) !== (answers[question.key] ?? "");
  });

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (status.kind === "saved" || status.kind === "failed" || status.kind === "unchanged") statusRef.current?.focus();
  }, [status]);

  function update(key: string, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
    setErrors((current) => Object.fromEntries(Object.entries(current).filter(([field]) => field !== key)));
    if (status.kind !== "saving") setStatus({ kind: "idle" });
  }

  async function save() {
    if (inFlight.current) return;
    const built = buildAnswers(step, draft, answers, isoDay(new Date()));
    setErrors(built.errors);
    const firstError = visible.find((question) => built.errors[question.key]);
    if (firstError) {
      requestAnimationFrame(() => document.getElementById(fieldId(firstError.key))?.focus());
      return;
    }
    if (changedCount(built.answers) === 0) {
      setStatus({ kind: "unchanged" });
      return;
    }
    const signature = JSON.stringify([revision, built.answers]);
    if (submission.current?.signature !== signature) submission.current = { signature, key: crypto.randomUUID() };
    inFlight.current = true;
    setStatus({ kind: "saving" });
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/steps/${encodeURIComponent(step.key)}/answers`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ expectedRevision: revision, submissionKey: submission.current.key, answers: built.answers }),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isWorkflowView(body.view, caseId)) {
        submission.current = null;
        setDraft(draftFrom(step, body.view.answers));
        setStatus({ kind: "saved" });
        onSaved(body.view);
        return;
      }
      if (response.status === 422) {
        const fields = Array.isArray(body?.fields) ? (body.fields as unknown[]).filter((f): f is string => typeof f === "string") : [];
        setErrors(
          Object.fromEntries(
            visible
              .filter((question) => fields.includes(question.key))
              .map((question) => [question.key, "HeroOS couldn't accept this answer. Please check it."]),
          ),
        );
      }
      const reason: Failure =
        response.status === 401
          ? "session_expired"
          : response.status === 403
            ? "forbidden"
            : response.status === 404
              ? "not_found"
              : response.status === 409
                ? "conflict"
                : response.status === 422
                  ? "invalid"
                  : "unavailable";
      // Keep the key only where a retry of the same change is the right move.
      if (reason !== "unavailable") submission.current = null;
      setStatus({ kind: "failed", reason });
    } catch {
      setStatus({ kind: "failed", reason: "unavailable" });
    } finally {
      inFlight.current = false;
    }
  }

  const saving = status.kind === "saving";
  const lead =
    missingCount === visible.length
      ? "Answer what you know; leave the rest for later."
      : missingCount > 0
        ? `${missingCount} still to answer. Answer what you know; leave the rest for later.`
        : "Everything here is answered. You can review or correct any answer.";
  return (
    <form
      aria-labelledby="composer-heading"
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div>
        <h2 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy outline-none" id="composer-heading" tabIndex={-1}>
          {step.title}
        </h2>
        <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">{step.intro}</p>
        <p className="mt-2 text-[0.9375rem] leading-relaxed text-hero-muted">
          {lead} Emptying an answer removes it when you save.
        </p>
        {step.provisional ? (
          <p className="mt-3 rounded-xl border border-hero-border bg-hero-bg px-3 py-2 text-sm leading-relaxed text-hero-navy/85">
            <span className="font-bold">Provisional.</span> These screening questions haven&apos;t been legally
            reviewed yet. They help decide when to pause and seek specialist advice; they aren&apos;t legal advice.
          </p>
        ) : null}
      </div>
      {visible.map((question) => (
        <QuestionField
          disabled={saving}
          error={errors[question.key]}
          key={question.key}
          onChange={(value) => update(question.key, value)}
          question={question}
          value={draft[question.key] ?? ""}
        />
      ))}

      <div aria-live="polite" className="outline-none" ref={statusRef} role="status" tabIndex={-1}>
        {status.kind === "saved" ? (
          <Notice title="Saved" tone="success">
            Your answers are saved to this case.
            {next ? (
              <>
                {" "}
                <button className="font-bold underline" onClick={next.go} type="button">
                  Continue to {next.title}
                </button>
              </>
            ) : null}
          </Notice>
        ) : status.kind === "unchanged" ? (
          <Notice title="Nothing new to save">Your answers already match what&apos;s saved.</Notice>
        ) : status.kind === "failed" ? (
          <Notice title={FAILURES[status.reason].title} tone={status.reason === "invalid" ? "caution" : "danger"}>
            {FAILURES[status.reason].body}
            {status.reason === "conflict" || status.reason === "forbidden" || status.reason === "not_found" ? (
              <>
                {" "}
                <button className="font-bold underline" onClick={() => window.location.reload()} type="button">
                  Reload the case
                </button>
              </>
            ) : status.reason === "session_expired" ? (
              <>
                {" "}
                <a className="font-bold underline" href="/auth/login">
                  Sign in
                </a>
              </>
            ) : null}
          </Notice>
        ) : null}
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
        {dirty ? (
          <button
            className={buttonQuiet}
            disabled={saving}
            onClick={() => {
              setDraft(draftFrom(step, answers));
              setErrors({});
              setStatus({ kind: "idle" });
            }}
            type="button"
          >
            Discard changes
          </button>
        ) : null}
        <button aria-disabled={saving} className={buttonPrimary} disabled={saving} type="submit">
          {saving ? "Saving…" : "Save answers"}
        </button>
      </div>
    </form>
  );
}
