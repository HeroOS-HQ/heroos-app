"use client";

import { useEffect, useRef, useState } from "react";

import { AlertIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, buttonSecondary, fieldError, hint, input, label } from "@/components/ui/styles";
import {
  API_FIELDS,
  checkDraft,
  type DecisionDraft,
  type DraftErrors,
  type DraftField,
  EMPTY_EVIDENCE,
  type EvidenceDraft,
  latestEventDay,
  requestBody,
} from "@/lib/workflows/decision-draft";
import type { DecisionOptions, DecisionRecord } from "@/lib/workflows/decisions";
import { isWorkflowView, type WorkflowView } from "@/lib/workflows/model";

/**
 * The decision-record form (M2-04): a new factual record, or a correction or
 * clarification of a record's current version (a new version; the earlier one
 * stays in the history). Every request carries the case revision it was based
 * on and a request key; a retry of the identical request after a lost
 * response reuses the key, so the API saves it once. The API takes the
 * recording administrator from the session and decides everything else.
 */

export type FormMode = { kind: "new" } | { kind: "correction" | "clarification"; record: DecisionRecord };
type Failure = "session_expired" | "forbidden" | "invalid" | "conflict" | "unavailable" | "not_found";

const FAILURES: Record<Failure, { title: string; body: string }> = {
  session_expired: {
    title: "Your session has ended",
    body: "Nothing was saved. Copy anything you don't want to lose, then sign in again.",
  },
  forbidden: {
    title: "Only company administrators can record decisions",
    body: "Your access may have changed. Reload the page to see the case as it is now.",
  },
  invalid: { title: "Some details need attention", body: "HeroOS couldn't accept the highlighted details." },
  conflict: {
    title: "This case has changed since you opened it",
    body: "Something was saved first, or this version was already corrected. Nothing was saved. Reload the case, then try again.",
  },
  not_found: { title: "This record can't be found", body: "It may not be available to you any more. Reload the page." },
  unavailable: {
    title: "Nothing was saved",
    body: "HeroOS couldn't be reached. Try again: if your record did go through, it won't be saved twice.",
  },
};

const ORDER: DraftField[] = [
  "category",
  "summary",
  "occurredOn",
  "decisionMaker",
  "decisionMakerRole",
  "explanation",
  "evidenceStatus",
  "evidence",
  "changeReason",
];
const FIELD_ID: Record<DraftField, string> = {
  category: "decision-category",
  summary: "decision-summary",
  occurredOn: "decision-date",
  decisionMaker: "decision-maker",
  decisionMakerRole: "decision-maker-role",
  explanation: "decision-explanation",
  evidenceStatus: "decision-evidence-status",
  evidence: "decision-evidence",
  changeReason: "decision-change-reason",
};
// Fields whose errors depend on another field's answer.
const RELATED: Partial<Record<DraftField, DraftField[]>> = {
  decisionMaker: ["decisionMaker", "decisionMakerRole"],
  evidenceStatus: ["evidenceStatus", "evidence"],
};
const optionClass = (checked: boolean) =>
  `flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-hero-blue ${
    checked ? "border-hero-blue bg-hero-blue-tint" : "border-hero-border bg-white hover:bg-hero-bg"
  }`;

function ErrorText({ id, error }: { id: string; error?: string }) {
  if (!error) return null;
  return (
    <p className={fieldError} id={`${id}-error`}>
      <AlertIcon className="mt-0.5 size-4 shrink-0" />
      <span>
        <span className="sr-only">Error: </span>
        {error}
      </span>
    </p>
  );
}

const describedBy = (id: string, error: string | undefined, help = false) =>
  [error ? `${id}-error` : null, help ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;

export function DecisionForm({
  companyId,
  caseId,
  options,
  mode,
  initial,
  revision,
  onSaved,
  onCancel,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  options: DecisionOptions;
  mode: FormMode;
  initial: DecisionDraft;
  revision: number;
  onSaved: (view: WorkflowView) => void;
  onCancel: () => void;
  fetcher?: typeof fetch;
}) {
  const [draft, setDraft] = useState(initial);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const request = useRef<{ signature: string; key: string } | null>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const limits = options.limits;
  const correcting = mode.kind !== "new";
  const todayUtc = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  // An edited field's error goes at once (the next save checks everything again).
  const clear = (...fields: DraftField[]) =>
    setErrors((current) => {
      if (!fields.some((field) => current[field])) return current;
      const next = { ...current };
      for (const field of fields) delete next[field];
      return next;
    });
  const set = <K extends keyof DecisionDraft>(key: K, value: DecisionDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    clear(...(RELATED[key] ?? [key]));
  };
  const setEvidence = (index: number, change: Partial<EvidenceDraft>) => {
    setDraft((current) => ({
      ...current,
      evidence: current.evidence.map((item, i) => (i === index ? { ...item, ...change } : item)),
    }));
    clear("evidence");
  };

  async function submit() {
    if (busy) return;
    const found = checkDraft(draft, limits, { correcting, todayUtc });
    setErrors(found);
    setFailure(null);
    const first = ORDER.find((field) => found[field]);
    if (first) {
      requestAnimationFrame(() => summaryRef.current?.focus());
      return;
    }
    const relation = mode.kind === "new" ? null : mode.kind;
    const payload = requestBody(draft, { expectedRevision: revision, requestKey: "", relation });
    const signature = JSON.stringify(payload);
    if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() };
    const base = `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/decisions`;
    const url = mode.kind === "new" ? base : `${base}/${encodeURIComponent(mode.record.id)}/corrections`;
    setBusy(true);
    try {
      const response = await (fetcher ?? fetch)(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ...payload, requestKey: request.current.key }),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        signal: AbortSignal.timeout(30_000),
      });
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isWorkflowView(body.view, caseId)) {
        request.current = null;
        onSaved(body.view);
        return;
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
      if (reason !== "unavailable") request.current = null;
      if (reason === "invalid" && body && Array.isArray(body.fields)) {
        const named: DraftErrors = {};
        for (const field of body.fields) {
          if (typeof field === "string" && field in API_FIELDS) named[API_FIELDS[field]] = "HeroOS couldn't accept this. Check it and try again.";
        }
        setErrors(named);
      }
      setFailure(reason);
      requestAnimationFrame(() => summaryRef.current?.focus());
    } catch {
      setFailure("unavailable");
    } finally {
      setBusy(false);
    }
  }

  const title =
    mode.kind === "new" ? "Add a record" : mode.kind === "correction" ? "Correct this record" : "Add a clarification";
  const listed = ORDER.filter((field) => errors[field]);
  const evidenceHeld = draft.evidenceStatus === "held";

  return (
    <form
      aria-labelledby="decision-form-heading"
      className="flex flex-col gap-6 rounded-2xl border border-hero-blue bg-white p-4 sm:p-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div>
        <h4 className="text-lg font-extrabold tracking-[-0.01em] text-hero-navy outline-none" id="decision-form-heading" ref={headingRef} tabIndex={-1}>
          {title}
        </h4>
        <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/85">
          {mode.kind === "new"
            ? "Record what your company did or decided, as a fact. Leave out names, health details and anything you don't need."
            : `You're writing a new version of “${mode.record.summary}”. The earlier version stays in the case history, marked as replaced.`}
        </p>
      </div>

      <div aria-live="polite" className="outline-none" ref={summaryRef} tabIndex={-1}>
        {failure ? (
          <Notice role="alert" title={FAILURES[failure].title} tone="danger">
            {FAILURES[failure].body}
          </Notice>
        ) : listed.length > 0 ? (
          <Notice role="alert" title="Some details need attention" tone="danger">
            <ul className="list-disc pl-5">
              {listed.map((field) => (
                <li key={field}>
                  <a className="font-semibold underline" href={`#${FIELD_ID[field]}`}>
                    {errors[field]}
                  </a>
                </li>
              ))}
            </ul>
          </Notice>
        ) : null}
      </div>

      <fieldset aria-describedby={describedBy(FIELD_ID.category, errors.category)} aria-invalid={errors.category ? true : undefined}>
        <legend className={label} id={FIELD_ID.category}>
          What are you recording?
        </legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {options.categories.map((choice) => (
            <label className={optionClass(draft.category === choice.key)} key={choice.key}>
              <input
                checked={draft.category === choice.key}
                className="mt-1 size-4 accent-hero-blue"
                disabled={busy}
                id={`decision-category-${choice.key}`}
                name="decision-category"
                onChange={() => set("category", choice.key)}
                type="radio"
                value={choice.key}
              />
              <span className="min-w-0">
                <span className="block font-bold text-hero-navy">{choice.label}</span>
                <span className="block text-sm leading-relaxed text-hero-navy/80">{choice.description}</span>
              </span>
            </label>
          ))}
        </div>
        <p className={hint}>{options.notRecordable}</p>
        <ErrorText error={errors.category} id={FIELD_ID.category} />
      </fieldset>

      <div>
        <label className={label} htmlFor={FIELD_ID.summary}>
          Short summary
        </label>
        <span className={hint} id={`${FIELD_ID.summary}-hint`}>
          One line, for example “Manager reviewed the shift handover logs”.
        </span>
        <input
          aria-describedby={describedBy(FIELD_ID.summary, errors.summary, true)}
          aria-invalid={errors.summary ? true : undefined}
          className={input}
          disabled={busy}
          id={FIELD_ID.summary}
          maxLength={limits.summary}
          onChange={(event) => set("summary", event.target.value)}
          type="text"
          value={draft.summary}
        />
        <ErrorText error={errors.summary} id={FIELD_ID.summary} />
      </div>

      <div>
        <label className={label} htmlFor={FIELD_ID.occurredOn}>
          When did it happen?
        </label>
        <input
          aria-describedby={describedBy(FIELD_ID.occurredOn, errors.occurredOn)}
          aria-invalid={errors.occurredOn ? true : undefined}
          className={`${input} sm:max-w-[14rem]`}
          disabled={busy}
          id={FIELD_ID.occurredOn}
          max={latestEventDay(todayUtc)}
          min="1990-01-01"
          onChange={(event) => set("occurredOn", event.target.value)}
          type="date"
          value={draft.occurredOn}
        />
        <ErrorText error={errors.occurredOn} id={FIELD_ID.occurredOn} />
      </div>

      <fieldset
        aria-describedby={describedBy(FIELD_ID.decisionMaker, errors.decisionMaker)}
        aria-invalid={errors.decisionMaker ? true : undefined}
      >
        <legend className={label} id={FIELD_ID.decisionMaker}>
          Who is responsible for this decision or record?
        </legend>
        <div className="mt-2 flex flex-col gap-2">
          {options.decisionMakers.map((choice) => (
            <label className={optionClass(draft.decisionMaker === choice.key)} key={choice.key}>
              <input
                checked={draft.decisionMaker === choice.key}
                className="mt-1 size-4 accent-hero-blue"
                disabled={busy}
                id={`decision-maker-${choice.key}`}
                name="decision-maker"
                onChange={() => set("decisionMaker", choice.key as "recorder" | "other")}
                type="radio"
                value={choice.key}
              />
              <span className="min-w-0">
                <span className="block font-bold text-hero-navy">{choice.label}</span>
                <span className="block text-sm leading-relaxed text-hero-navy/80">{choice.description}</span>
              </span>
            </label>
          ))}
        </div>
        <ErrorText error={errors.decisionMaker} id={FIELD_ID.decisionMaker} />
        {draft.decisionMaker === "other" ? (
          <div className="mt-3">
            <label className={label} htmlFor={FIELD_ID.decisionMakerRole}>
              Their role or job title
            </label>
            <span className={hint} id={`${FIELD_ID.decisionMakerRole}-hint`}>
              Recorded as your company states it. HeroOS doesn&apos;t verify it, and you remain the person who recorded it.
            </span>
            <input
              aria-describedby={describedBy(FIELD_ID.decisionMakerRole, errors.decisionMakerRole, true)}
              aria-invalid={errors.decisionMakerRole ? true : undefined}
              className={input}
              disabled={busy}
              id={FIELD_ID.decisionMakerRole}
              maxLength={limits.decisionMakerRole}
              onChange={(event) => set("decisionMakerRole", event.target.value)}
              type="text"
              value={draft.decisionMakerRole}
            />
            <ErrorText error={errors.decisionMakerRole} id={FIELD_ID.decisionMakerRole} />
          </div>
        ) : null}
      </fieldset>

      <div>
        <label className={label} htmlFor={FIELD_ID.explanation}>
          What happened, and why?
        </label>
        <span className={hint} id={`${FIELD_ID.explanation}-hint`}>
          The facts as your company sees them. A summary is enough: you don&apos;t need to repeat every allegation.
        </span>
        <textarea
          aria-describedby={describedBy(FIELD_ID.explanation, errors.explanation, true)}
          aria-invalid={errors.explanation ? true : undefined}
          className={`${input} min-h-32 resize-y leading-relaxed`}
          disabled={busy}
          id={FIELD_ID.explanation}
          maxLength={limits.explanation}
          onChange={(event) => set("explanation", event.target.value)}
          rows={5}
          value={draft.explanation}
        />
        <p className="mt-1 text-right text-sm text-hero-muted">
          {draft.explanation.length.toLocaleString("en-GB")} / {limits.explanation.toLocaleString("en-GB")} characters
        </p>
        <ErrorText error={errors.explanation} id={FIELD_ID.explanation} />
      </div>

      <fieldset
        aria-describedby={describedBy(FIELD_ID.evidenceStatus, errors.evidenceStatus ?? errors.evidence, true)}
        aria-invalid={errors.evidenceStatus || errors.evidence ? true : undefined}
      >
        <legend className={label} id={FIELD_ID.evidenceStatus}>
          Is there supporting evidence?
        </legend>
        <span className={hint} id={`${FIELD_ID.evidenceStatus}-hint`}>
          {options.evidenceNotice}
        </span>
        <div className="mt-2 flex flex-col gap-2">
          {options.evidenceStatuses.map((choice) => (
            <label className={optionClass(draft.evidenceStatus === choice.key)} key={choice.key}>
              <input
                checked={draft.evidenceStatus === choice.key}
                className="mt-1 size-4 accent-hero-blue"
                disabled={busy}
                id={`decision-evidence-${choice.key}`}
                name="decision-evidence-status"
                onChange={() => {
                  setDraft((current) => ({
                    ...current,
                    evidenceStatus: choice.key as DecisionDraft["evidenceStatus"],
                    evidence: choice.key === "held" && current.evidence.length === 0 ? [{ ...EMPTY_EVIDENCE }] : current.evidence,
                  }));
                  clear("evidenceStatus", "evidence");
                }}
                type="radio"
                value={choice.key}
              />
              <span className="min-w-0">
                <span className="block font-bold text-hero-navy">{choice.label}</span>
                <span className="block text-sm leading-relaxed text-hero-navy/80">{choice.description}</span>
              </span>
            </label>
          ))}
        </div>
        <ErrorText error={errors.evidenceStatus} id={FIELD_ID.evidenceStatus} />
        {evidenceHeld ? (
          <div className="mt-3 flex flex-col gap-3" id={FIELD_ID.evidence}>
            {draft.evidence.map((item, index) => (
              <div className="rounded-xl border border-hero-border p-3.5" key={index}>
                <div className="grid gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
                  <div>
                    <label className={label} htmlFor={`decision-evidence-${index}-kind`}>
                      Type
                    </label>
                    <select
                      className={input}
                      disabled={busy}
                      id={`decision-evidence-${index}-kind`}
                      onChange={(event) => setEvidence(index, { kind: event.target.value as EvidenceDraft["kind"] })}
                      value={item.kind}
                    >
                      <option value="">Choose…</option>
                      {options.evidenceKinds.map((kind) => (
                        <option key={kind.key} value={kind.key}>
                          {kind.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className={label} htmlFor={`decision-evidence-${index}-description`}>
                      Description
                    </label>
                    <input
                      className={input}
                      disabled={busy}
                      id={`decision-evidence-${index}-description`}
                      maxLength={limits.evidenceDescription}
                      onChange={(event) => setEvidence(index, { description: event.target.value })}
                      type="text"
                      value={item.description}
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <label className={label} htmlFor={`decision-evidence-${index}-reference`}>
                    Where it&apos;s kept (optional)
                  </label>
                  <span className={hint}>A reference number or folder name, not a link.</span>
                  <input
                    className={input}
                    disabled={busy}
                    id={`decision-evidence-${index}-reference`}
                    maxLength={limits.evidenceReference}
                    onChange={(event) => setEvidence(index, { reference: event.target.value })}
                    type="text"
                    value={item.reference}
                  />
                </div>
                {draft.evidence.length > 1 ? (
                  <button
                    className={`${buttonQuiet} mt-2 text-sm`}
                    disabled={busy}
                    onClick={() => {
                      setDraft((current) => ({ ...current, evidence: current.evidence.filter((_, i) => i !== index) }));
                      clear("evidence");
                    }}
                    type="button"
                  >
                    Remove this item
                  </button>
                ) : null}
              </div>
            ))}
            {draft.evidence.length < limits.evidenceItems ? (
              <button
                className={`${buttonQuiet} self-start`}
                disabled={busy}
                onClick={() => setDraft((current) => ({ ...current, evidence: [...current.evidence, { ...EMPTY_EVIDENCE }] }))}
                type="button"
              >
                Add another item
              </button>
            ) : null}
            <ErrorText error={errors.evidence} id={FIELD_ID.evidence} />
          </div>
        ) : null}
      </fieldset>

      {correcting ? (
        <div>
          <label className={label} htmlFor={FIELD_ID.changeReason}>
            {mode.kind === "correction" ? "Why are you correcting it?" : "What are you adding, and why?"}
          </label>
          <span className={hint} id={`${FIELD_ID.changeReason}-hint`}>
            For example “The meeting date was wrong” or “Added where the notes are kept”.
          </span>
          <textarea
            aria-describedby={describedBy(FIELD_ID.changeReason, errors.changeReason, true)}
            aria-invalid={errors.changeReason ? true : undefined}
            className={`${input} min-h-24 resize-y leading-relaxed`}
            disabled={busy}
            id={FIELD_ID.changeReason}
            maxLength={limits.changeReason}
            onChange={(event) => set("changeReason", event.target.value)}
            rows={3}
            value={draft.changeReason}
          />
          <ErrorText error={errors.changeReason} id={FIELD_ID.changeReason} />
        </div>
      ) : null}

      <p className="text-sm leading-relaxed text-hero-muted">
        Saving adds this to the case history as your company&apos;s record. It doesn&apos;t move the case to another stage,
        release a hold, or count as a warning or any other outcome.
      </p>
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
        <button className={buttonSecondary} disabled={busy} onClick={onCancel} type="button">
          Cancel
        </button>
        <button className={buttonPrimary} disabled={busy} type="submit">
          {busy ? "Saving…" : mode.kind === "new" ? "Save record" : mode.kind === "correction" ? "Save correction" : "Save clarification"}
        </button>
      </div>
    </form>
  );
}
