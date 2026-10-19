"use client";

import { useEffect, useRef, useState } from "react";

import { AlertIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, buttonSecondary, fieldError, hint, input, label } from "@/components/ui/styles";
import {
  checkDraft,
  type DraftChoices,
  type DraftErrors,
  type DraftValues,
  initialValues,
  previewBody,
  toggleChoice,
} from "@/lib/documents/draft";
import { type FieldSpec, isPreview, KIND_LABEL, type Preview, type TemplateForm } from "@/lib/documents/model";

import { DocumentBlocks, DocumentPreview } from "./document-preview";

/**
 * A template's form and its preview (M2-04C). What the administrator types
 * stays in this page's memory: it is sent only to draw the preview, and the
 * API keeps nothing. Inputs opt out of the browser's autofill history so
 * personal details aren't remembered by the browser either. The API decides
 * whether the template can be previewed now and checks every value again.
 */

type Failure = "session_expired" | "forbidden" | "not_found" | "conflict" | "invalid" | "too_large" | "unavailable";

const FAILURES: Record<Failure, { title: string; body: string }> = {
  session_expired: {
    title: "Your session has ended",
    body: "Nothing was kept. Copy anything you don't want to lose, then sign in again.",
  },
  forbidden: {
    title: "Only company administrators can preview documents",
    body: "Your access may have changed. Reload the page to see the case as it is now.",
  },
  not_found: { title: "This template isn't available", body: "It may have been removed. Reload the page." },
  conflict: {
    title: "This template can't be previewed now",
    body: "The case or the template changed since you opened it. Reload the case to see what's available.",
  },
  invalid: { title: "Some details need attention", body: "HeroOS couldn't accept the highlighted details." },
  too_large: { title: "Too much text", body: "Shorten the longest details, then try again." },
  unavailable: { title: "The preview couldn't be shown", body: "HeroOS couldn't be reached. Try again." },
};

const fieldId = (key: string) => `document-field-${key.replace(/\./g, "-")}`;

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

function FieldInput({
  field,
  value,
  error,
  reminder,
  busy,
  onChange,
}: {
  field: FieldSpec;
  value: string | string[];
  error?: string;
  reminder: string;
  busy: boolean;
  onChange: (value: string | string[]) => void;
}) {
  const id = fieldId(field.key);
  const hints = [field.help, field.suggested !== null ? "Suggested from this case. You can change or clear it." : null, field.reminder ? reminder : null].filter(
    (item): item is string => item !== null,
  );
  const describedBy = [error ? `${id}-error` : null, hints.length > 0 ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  const common = {
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
    autoComplete: "off",
    className: input,
    disabled: busy,
  } as const;

  if (field.kind === "list") {
    const entries = Array.isArray(value) ? value : [value];
    return (
      <fieldset aria-describedby={describedBy} aria-invalid={error ? true : undefined}>
        <legend className={label} id={id}>
          {field.label}
        </legend>
        {hints.length > 0 ? (
          <span className={hint} id={`${id}-hint`}>
            {hints.join(" ")}
          </span>
        ) : null}
        <div className="flex flex-col gap-2">
          {entries.map((entry, index) => (
            <div className="flex items-end gap-2" key={index}>
              <div className="min-w-0 flex-1">
                <label className="sr-only" htmlFor={`${id}-${index}`}>
                  {field.label}, entry {index + 1}
                </label>
                <input
                  {...common}
                  id={`${id}-${index}`}
                  maxLength={field.maxLength ?? undefined}
                  onChange={(event) => onChange(entries.map((item, i) => (i === index ? event.target.value : item)))}
                  type="text"
                  value={entry}
                />
              </div>
              {entries.length > 1 ? (
                <button
                  className={`${buttonQuiet} mb-1 text-sm`}
                  disabled={busy}
                  onClick={() => onChange(entries.filter((_, i) => i !== index))}
                  type="button"
                >
                  Remove<span className="sr-only"> entry {index + 1}</span>
                </button>
              ) : null}
            </div>
          ))}
        </div>
        {field.maxItems !== null && entries.length < field.maxItems ? (
          <button className={`${buttonQuiet} mt-1`} disabled={busy} onClick={() => onChange([...entries, ""])} type="button">
            Add another entry
          </button>
        ) : null}
        <ErrorText error={error} id={id} />
      </fieldset>
    );
  }

  const text = Array.isArray(value) ? value.join(" ") : value;
  return (
    <div>
      <label className={label} htmlFor={id}>
        {field.label}
      </label>
      {hints.length > 0 ? (
        <span className={hint} id={`${id}-hint`}>
          {hints.join(" ")}
        </span>
      ) : null}
      {field.kind === "long_text" ? (
        <textarea
          {...common}
          className={`${input} min-h-28 resize-y leading-relaxed`}
          id={id}
          maxLength={field.maxLength ?? undefined}
          onChange={(event) => onChange(event.target.value)}
          rows={4}
          value={text}
        />
      ) : (
        <input
          {...common}
          className={field.kind === "date" ? `${input} sm:max-w-[14rem]` : input}
          id={id}
          max={field.kind === "date" ? "2100-12-31" : undefined}
          maxLength={field.kind === "date" ? undefined : (field.maxLength ?? undefined)}
          min={field.kind === "date" ? "1990-01-01" : undefined}
          onChange={(event) => onChange(event.target.value)}
          type={field.kind === "date" ? "date" : "text"}
          value={text}
        />
      )}
      <ErrorText error={error} id={id} />
    </div>
  );
}

export function DocumentForm({
  companyId,
  caseId,
  form,
  onClose,
  fetcher,
}: {
  companyId: string;
  caseId: string;
  form: TemplateForm;
  onClose: () => void;
  fetcher?: typeof fetch;
}) {
  const [values, setValues] = useState<DraftValues>(() => initialValues(form));
  const [choices, setChoices] = useState<DraftChoices>({});
  const [errors, setErrors] = useState<DraftErrors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const previewId = `document-preview-${form.template.code}`;

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const set = (key: string, value: string | string[]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  async function showPreview() {
    if (busy) return;
    const found = checkDraft(form, values);
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) {
      requestAnimationFrame(() => summaryRef.current?.focus());
      return;
    }
    setBusy(true);
    try {
      const response = await (fetcher ?? fetch)(
        `/bff/companies/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(form.template.key)}/preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(previewBody(form, values, choices)),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        },
      );
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isPreview(body.preview)) {
        setPreview(body.preview);
        requestAnimationFrame(() => document.getElementById(previewId)?.focus());
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
                : response.status === 413
                  ? "too_large"
                  : response.status === 422
                    ? "invalid"
                    : "unavailable";
      if (reason === "invalid" && body && Array.isArray(body.fields)) {
        const named: DraftErrors = {};
        for (const key of body.fields) {
          if (typeof key === "string" && form.fields.some((field) => field.key === key)) {
            named[key] = "HeroOS couldn't accept this. Check it and try again.";
          }
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

  const listed = form.fields.filter((field) => errors[field.key]);
  const headingId = `document-form-heading-${form.template.code}`;

  return (
    <div className="flex flex-col gap-6">
      <form
        aria-labelledby={headingId}
        autoComplete="off"
        className="flex flex-col gap-6 rounded-2xl border border-hero-blue bg-white p-4 sm:p-6"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void showPreview();
        }}
      >
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.08em] text-hero-blue-ink">
            {form.template.code} · {KIND_LABEL[form.template.kind] ?? "Document"}
          </p>
          <h4 className="mt-1 text-lg font-extrabold tracking-[-0.01em] text-hero-navy outline-none" id={headingId} ref={headingRef} tabIndex={-1}>
            {form.template.title}
          </h4>
        </div>

        <Notice title="Preview only">
          <p>{form.notice}</p>
          {form.bundle.notice ? (
            <p className="mt-2">
              <strong>{form.bundle.notice.title}.</strong> {form.bundle.notice.body}
            </p>
          ) : null}
        </Notice>

        {form.instructions.length > 0 ? (
          <details className="rounded-xl border border-hero-border bg-hero-bg px-4 py-3" open>
            <summary className="cursor-pointer text-sm font-bold text-hero-navy">Instructions for you (not part of the document)</summary>
            <div className="mt-2 text-sm leading-relaxed text-hero-navy/85">
              <DocumentBlocks blocks={form.instructions} />
            </div>
          </details>
        ) : null}

        <div aria-live="polite" className="outline-none" ref={summaryRef} tabIndex={-1}>
          {failure ? (
            <Notice role="alert" title={FAILURES[failure].title} tone="danger">
              {FAILURES[failure].body}
            </Notice>
          ) : listed.length > 0 ? (
            <Notice role="alert" title="Some details need attention" tone="danger">
              <ul className="list-disc pl-5">
                {listed.map((field) => (
                  <li key={field.key}>
                    <a className="font-semibold underline" href={`#${fieldId(field.key)}`}>
                      {field.label}: {errors[field.key]}
                    </a>
                  </li>
                ))}
              </ul>
            </Notice>
          ) : null}
        </div>

        {form.choices.map((choice) => {
          const selected = choices[choice.key] ?? [];
          return (
            <fieldset key={choice.key}>
              <legend className={label}>{choice.label}</legend>
              {choice.help ? <span className={hint}>{choice.help}</span> : null}
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                {choice.options.map((option) => (
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3 has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-hero-blue ${
                      selected.includes(option.value) ? "border-hero-blue bg-hero-blue-tint" : "border-hero-border bg-white hover:bg-hero-bg"
                    }`}
                    key={option.value}
                  >
                    <input
                      checked={selected.includes(option.value)}
                      className="size-4 accent-hero-blue"
                      disabled={busy}
                      name={`document-choice-${choice.key}`}
                      onChange={() => setChoices((current) => ({ ...current, [choice.key]: toggleChoice(choice, current[choice.key] ?? [], option.value) }))}
                      type={choice.multiple ? "checkbox" : "radio"}
                      value={option.value}
                    />
                    <span className="font-semibold text-hero-navy">{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}

        {form.fields.map((field) => (
          <FieldInput
            busy={busy}
            error={errors[field.key]}
            field={field}
            key={field.key}
            onChange={(value) => set(field.key, value)}
            reminder={form.reminder}
            value={values[field.key] ?? ""}
          />
        ))}

        <p className="text-sm leading-relaxed text-hero-muted">
          Showing a preview sends these details to HeroOS only to draw it. Nothing is saved, and the case doesn&apos;t change.
          Anything you leave empty shows as a gap.
        </p>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
          <button className={buttonSecondary} disabled={busy} onClick={onClose} type="button">
            Close
          </button>
          <button className={buttonPrimary} disabled={busy} type="submit">
            {busy ? "Preparing preview…" : preview ? "Update preview" : "Show preview"}
          </button>
        </div>
      </form>

      {preview ? <DocumentPreview headingId={previewId} preview={preview} /> : null}
    </div>
  );
}
