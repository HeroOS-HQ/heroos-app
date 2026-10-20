"use client";

import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { outlineButton, primaryButton, sheet } from "@/components/app/workspace-chrome";
import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BuildingIcon,
  CheckCircleIcon,
  CheckIcon,
  CloseIcon,
  InfoIcon,
  ScaleIcon,
} from "@/components/site/icons";
import {
  attentionOf,
  type BlueprintForm,
  buildPatch,
  changedLabels,
  type EditableField,
  editedFields,
  FIELD_IDS,
  FIELD_ORDER,
  formFrom,
  jurisdictionDisplay,
} from "@/lib/blueprint/model";
import { type FieldErrors, LIMITS } from "@/lib/onboarding/model";
import type { Blueprint } from "@/lib/server/heroos-api";
import { formatDay } from "@/lib/workflows/copy";

/**
 * Page 2, Company Blueprint (approved Oct 20 design): the company context
 * HeroOS uses. Read first: one sheet. One "Edit Blueprint" makes everything
 * editable; a save bar appears only once something has changed, and nothing
 * is saved until "Save changes". It edits the Blueprint the API keeps
 * (`PATCH /bff/companies/{id}/blueprint`); the API enforces the administrator
 * role on every save, whatever this page shows.
 */

type Failure = "session_expired" | "forbidden" | "invalid" | "unavailable";
type Status = { kind: "idle" } | { kind: "saving" } | { kind: "failed"; reason: Failure };

const FAILURES: Record<Failure, string> = {
  session_expired: "Your session has ended, so your changes weren't saved. Sign in again to continue.",
  forbidden: "Your changes weren't saved. Only company administrators can edit the Blueprint, and your access may have changed.",
  invalid: "Your changes weren't saved. Check the highlighted details and try again.",
  unavailable: "HeroOS didn't confirm the update. Please try again.",
};

const SERVER_FIELD_MESSAGE = "HeroOS couldn't accept this value. Please check it and try again.";

const fieldLabel = "flex items-center gap-2 text-[0.875rem] font-bold text-hero-navy";
const fieldHint = "mt-1 text-[0.8125rem] leading-relaxed text-hero-muted";
const input =
  "mt-1.5 block min-h-12 w-full rounded-xl border border-hero-navy/15 bg-white px-4 text-base text-hero-navy shadow-[inset_0_1px_2px_rgb(14_30_61/0.04)] transition-[border-color,box-shadow] duration-150 placeholder:text-hero-muted/80 focus:border-hero-blue focus:shadow-[0_0_0_4px_rgb(61_107_196/0.12)] focus-visible:outline-none aria-[invalid=true]:border-hero-danger";
const editedInput = "border-hero-blue/60 bg-[#fbfdff]";
const editButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-hero-yellow px-5 text-[0.9375rem] font-bold text-hero-navy shadow-[0_8px_20px_-12px_rgb(255_212_1/0.95)] transition-colors duration-150 hover:bg-[#f6cb00]";

function isBlueprint(value: unknown, companyId: string): value is Blueprint {
  if (typeof value !== "object" || value === null) return false;
  const blueprint = value as Partial<Blueprint>;
  return (
    blueprint.companyId === companyId &&
    typeof blueprint.licensing === "object" &&
    blueprint.licensing !== null &&
    typeof blueprint.jurisdiction === "object" &&
    blueprint.jurisdiction !== null
  );
}

/* ------------------------------------------------------------- primitives */

/** "Edited": words and a dot, never colour alone. */
function Edited() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-hero-blue-tint px-2 py-0.5 text-[0.6875rem] font-bold text-hero-blue-ink">
      <span aria-hidden="true" className="size-1.5 rounded-full bg-hero-blue" />
      Edited
    </span>
  );
}

function Updated() {
  return (
    <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-hero-success-tint px-2 py-0.5 align-middle text-[0.6875rem] font-bold text-hero-success">
      <CheckIcon className="size-3" />
      Updated
    </span>
  );
}

function Missing({ children = "Not added yet" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-[#8a4a00]">
      <AlertIcon className="size-4 shrink-0" />
      {children}
    </span>
  );
}

/** One section of the sheet: its name and purpose on the left, the details on the right. */
function Section({
  id,
  icon,
  title,
  line,
  attention = false,
  children,
}: {
  id: string;
  icon: ReactNode;
  title: string;
  line: string;
  attention?: boolean;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid scroll-mt-24 gap-x-10 gap-y-3 border-t border-hero-border py-6 first:border-t-0 sm:py-7 md:grid-cols-[15.5rem_minmax(0,1fr)]"
      id={id}
    >
      <div>
        <div className="flex items-center gap-2.5">
          <span className="text-hero-muted">{icon}</span>
          <h2 className="text-[1.0625rem] font-extrabold tracking-[-0.01em] text-hero-navy" id={`${id}-title`}>
            {title}
          </h2>
        </div>
        <p className="mt-1 text-[0.875rem] leading-relaxed text-hero-muted md:pl-[1.875rem]">{line}</p>
        {attention ? (
          <p className="mt-1 text-[0.8125rem] md:pl-[1.875rem]">
            <Missing>Needs attention</Missing>
          </p>
        ) : null}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function Row({ label, children, updated = false }: { label: string; children: ReactNode; updated?: boolean }) {
  return (
    <div className="grid gap-0.5 py-2.5 sm:grid-cols-[10.5rem_minmax(0,1fr)] sm:gap-6">
      <dt className="text-[0.875rem] text-hero-muted">
        {label}
        {updated ? <Updated /> : null}
      </dt>
      <dd className="min-w-0 break-words text-[0.9375rem] font-semibold leading-relaxed text-hero-navy">{children}</dd>
    </div>
  );
}

const notAdded = <span className="font-normal text-hero-muted">Not added</span>;

/* ------------------------------------------------------------ read view */

function ReadSheet({ companyName, blueprint, updated }: { companyName: string; blueprint: Blueprint; updated: Set<string> }) {
  const missing = new Set(attentionOf(blueprint).map((item) => item.field));
  const jurisdiction = jurisdictionDisplay(blueprint);
  return (
    <div>
      <Section icon={<BuildingIcon className="size-5" />} id="basics" line="Who you are and what you do." title="Company basics">
        <dl className="divide-y divide-hero-border">
          <Row label="Company name">{companyName}</Row>
          <Row label="Legal company name" updated={updated.has("Legal company name")}>
            {blueprint.legalName ?? notAdded}
          </Row>
          <Row label="Industry" updated={updated.has("Industry")}>
            {blueprint.industry ?? notAdded}
          </Row>
          <Row label="Number of employees" updated={updated.has("Number of employees")}>
            {blueprint.employeeCount ?? notAdded}
          </Row>
        </dl>
      </Section>

      {/* The company's current setting, shown plainly: no badge that could read as a legal verification. */}
      <Section
        attention={missing.has("licensingLocation") || missing.has("licensingAuthority")}
        icon={<ScaleIcon className="size-5" />}
        id="jurisdiction"
        line="Which employment rules apply to you."
        title="Jurisdiction"
      >
        {jurisdiction.kind === "missing" ? (
          <>
            <p className="pt-1 text-[1.0625rem]">
              <Missing>Jurisdiction not selected</Missing>
            </p>
            <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">{jurisdiction.note}</p>
          </>
        ) : (
          <>
            <p className="pt-0.5 text-[1.5rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy">
              {jurisdiction.label}
              {updated.has("Jurisdiction") ? <Updated /> : null}
            </p>
            {jurisdiction.detail ? <p className="mt-0.5 text-[0.9375rem] text-hero-muted">{jurisdiction.detail}</p> : null}
            {jurisdiction.note ? (
              <p className="mt-3 flex gap-2 text-[0.8125rem] leading-relaxed text-hero-muted">
                <InfoIcon className="mt-0.5 size-4 shrink-0" />
                {jurisdiction.note}
              </p>
            ) : null}
          </>
        )}
      </Section>
    </div>
  );
}

/* ------------------------------------------------------------ edit view */

function Field({
  id,
  label,
  hint,
  edited = false,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  edited?: boolean;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="scroll-mt-24">
      <label className={fieldLabel} htmlFor={id}>
        {label}
        {edited ? <Edited /> : null}
      </label>
      {hint ? (
        <p className={fieldHint} id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p className="mt-1.5 flex items-start gap-1.5 text-[0.875rem] font-semibold text-hero-danger" id={`${id}-error`}>
          <AlertIcon className="mt-0.5 size-4 shrink-0" />
          <span>
            <span className="sr-only">Error: </span>
            {error}
          </span>
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint: boolean, error: string | undefined): string | undefined {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

function Choice({
  id,
  value,
  checked,
  title,
  hint,
  onChoose,
  children,
}: {
  id: string;
  value: string;
  checked: boolean;
  title: string;
  hint: string;
  onChoose: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-hero-navy/12 bg-white px-4 py-3 transition-colors duration-150 hover:border-hero-blue/50 has-[:checked]:border-hero-blue has-[:checked]:bg-[#f5f8fe] has-[:focus-visible]:shadow-[0_0_0_4px_rgb(61_107_196/0.15)]">
      <label className="flex cursor-pointer gap-3" htmlFor={id}>
        <input
          checked={checked}
          className="mt-1 size-4 shrink-0 accent-hero-navy focus-visible:outline-none"
          id={id}
          name="bp-jurisdiction"
          onChange={onChoose}
          type="radio"
          value={value}
        />
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-hero-navy">{title}</span>
          <span className="block text-[0.8125rem] leading-relaxed text-hero-muted">{hint}</span>
        </span>
      </label>
      {children}
    </div>
  );
}

function EditSheet({
  companyName,
  form,
  edited,
  errors,
  update,
}: {
  companyName: string;
  form: BlueprintForm;
  edited: Set<EditableField>;
  errors: FieldErrors;
  update: <K extends keyof BlueprintForm>(key: K, value: BlueprintForm[K]) => void;
}) {
  return (
    <div>
      <Section icon={<BuildingIcon className="size-5" />} id="basics" line="Who you are and what you do." title="Company basics">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className={fieldLabel}>Company name</p>
            <p className="mt-1.5 flex min-h-12 items-center break-words rounded-xl bg-hero-navy/[0.04] px-4 text-base font-semibold text-hero-navy">
              {companyName}
            </p>
            <p className={fieldHint}>Your workspace name can&apos;t be changed here yet.</p>
          </div>
          <Field edited={edited.has("legalName")} error={errors.legalName} id={FIELD_IDS.legalName} label="Legal company name">
            <input
              aria-describedby={describedBy(FIELD_IDS.legalName, false, errors.legalName)}
              aria-invalid={errors.legalName ? true : undefined}
              autoComplete="off"
              className={`${input} ${edited.has("legalName") ? editedInput : ""}`}
              id={FIELD_IDS.legalName}
              maxLength={LIMITS.legalName + 20}
              onChange={(event) => update("legalName", event.target.value)}
              placeholder="As shown on your business licence"
              type="text"
              value={form.legalName}
            />
          </Field>
          <Field edited={edited.has("industry")} error={errors.industry} id={FIELD_IDS.industry} label="Industry">
            <input
              aria-describedby={describedBy(FIELD_IDS.industry, false, errors.industry)}
              aria-invalid={errors.industry ? true : undefined}
              autoComplete="off"
              className={`${input} ${edited.has("industry") ? editedInput : ""}`}
              id={FIELD_IDS.industry}
              maxLength={LIMITS.industry + 20}
              onChange={(event) => update("industry", event.target.value)}
              placeholder="For example: retail"
              type="text"
              value={form.industry}
            />
          </Field>
          <Field
            edited={edited.has("employeeCount")}
            error={errors.employeeCount}
            id={FIELD_IDS.employeeCount}
            label="Number of employees"
          >
            <input
              aria-describedby={describedBy(FIELD_IDS.employeeCount, false, errors.employeeCount)}
              aria-invalid={errors.employeeCount ? true : undefined}
              autoComplete="off"
              className={`${input} ${edited.has("employeeCount") ? editedInput : ""}`}
              id={FIELD_IDS.employeeCount}
              inputMode="numeric"
              onChange={(event) => update("employeeCount", event.target.value)}
              placeholder="For example: 24"
              type="text"
              value={form.employeeCount}
            />
          </Field>
        </div>
      </Section>

      <Section icon={<ScaleIcon className="size-5" />} id="jurisdiction" line="Which employment rules apply to you." title="Jurisdiction">
        <fieldset aria-describedby={errors.licensingLocation ? "bp-jurisdiction-error" : undefined} className="scroll-mt-24">
          <legend className={fieldLabel}>
            Jurisdiction
            {edited.has("licensingLocation") ? <Edited /> : null}
          </legend>
          <div className="mt-2 grid gap-2.5">
            <Choice
              checked={form.licensingLocation === "difc"}
              hint="Dubai International Financial Centre"
              id="bp-jurisdiction-difc"
              onChoose={() => update("licensingLocation", "difc")}
              title="DIFC"
              value="difc"
            />
            <Choice
              checked={form.licensingLocation === "other"}
              hint="Another free zone, or the UAE mainland. Add the authority's name."
              id="bp-jurisdiction-other"
              onChoose={() => update("licensingLocation", "other")}
              title="Another jurisdiction"
              value="other"
            >
              {form.licensingLocation === "other" ? (
                <div className="mt-3 pl-7">
                  <Field error={errors.licensingAuthority} id={FIELD_IDS.licensingAuthority} label="Licensing authority">
                    <input
                      aria-describedby={describedBy(FIELD_IDS.licensingAuthority, false, errors.licensingAuthority)}
                      aria-invalid={errors.licensingAuthority ? true : undefined}
                      autoComplete="off"
                      className={input}
                      id={FIELD_IDS.licensingAuthority}
                      maxLength={LIMITS.licensingAuthority + 20}
                      onChange={(event) => update("licensingAuthority", event.target.value)}
                      placeholder="As shown on your business licence"
                      type="text"
                      value={form.licensingAuthority}
                    />
                  </Field>
                </div>
              ) : null}
            </Choice>
            <Choice
              checked={form.licensingLocation === "not_sure"}
              hint="You can add it later."
              id="bp-jurisdiction-not-sure"
              onChoose={() => update("licensingLocation", "not_sure")}
              title="Not sure yet"
              value="not_sure"
            />
          </div>
        </fieldset>
        <p className="mt-3 flex gap-2 text-[0.8125rem] leading-relaxed text-hero-muted">
          <InfoIcon className="mt-0.5 size-4 shrink-0" />
          If you change it, jurisdiction-specific guidance may be unavailable until the new setting is in place.
        </p>
      </Section>
    </div>
  );
}

/* --------------------------------------------------------------- the page */

export function BlueprintPage({
  companyId,
  companyName,
  initial,
  editable,
  fetcher,
}: {
  companyId: string;
  companyName: string;
  initial: Blueprint;
  /** The API's answer: this account may update the Blueprint. */
  editable: boolean;
  fetcher?: typeof fetch;
}) {
  const [saved, setSaved] = useState(initial);
  const [form, setForm] = useState<BlueprintForm>(() => formFrom(initial));
  const [editing, setEditing] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  // What the last save changed, for the confirmation and the "Updated" markers.
  const [justSaved, setJustSaved] = useState<string[] | null>(null);
  const inFlight = useRef(false);
  const statusRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  const pending = buildPatch(form, saved);
  const changes = changedLabels(pending.patch);
  const edited = editedFields(form, saved);
  const dirty = editing && edited.size > 0;
  const attention = attentionOf(saved);
  const base = `/workspaces/${encodeURIComponent(companyId)}`;

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (status.kind === "failed" || justSaved) statusRef.current?.focus();
  }, [status, justSaved]);

  function update<K extends keyof BlueprintForm>(key: K, value: BlueprintForm[K]) {
    setForm((current) => {
      const next = { ...current, [key]: value };
      // Changing away from "Another jurisdiction" drops the authority it needed.
      if (key === "licensingLocation" && value !== "other") next.licensingAuthority = "";
      return next;
    });
    setErrors((current) => Object.fromEntries(Object.entries(current).filter(([field]) => field !== key)));
    if (status.kind === "failed") setStatus({ kind: "idle" });
  }

  function startEditing(focus?: EditableField) {
    setForm(formFrom(saved));
    setErrors({});
    setStatus({ kind: "idle" });
    setJustSaved(null);
    setEditing(true);
    requestAnimationFrame(() => {
      const target = focus ? document.getElementById(FIELD_IDS[focus]) : document.getElementById(FIELD_IDS.legalName);
      target?.focus();
    });
  }

  function discard() {
    setForm(formFrom(saved));
    setErrors({});
    setStatus({ kind: "idle" });
    setEditing(false);
  }

  async function save() {
    if (inFlight.current) return;
    const { patch, errors: found } = buildPatch(form, saved);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      const first = FIELD_ORDER.find((field) => found[field]);
      if (first) requestAnimationFrame(() => document.getElementById(FIELD_IDS[first])?.focus());
      setStatus({ kind: "failed", reason: "invalid" });
      return;
    }
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    inFlight.current = true;
    setStatus({ kind: "saving" });
    try {
      const response = await (fetcher ?? fetch)(`/bff/companies/${encodeURIComponent(companyId)}/blueprint`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(patch),
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        signal: AbortSignal.timeout(30_000),
      });
      const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
      if (response.status === 200 && body && isBlueprint(body.blueprint, companyId)) {
        setSaved(body.blueprint);
        setForm(formFrom(body.blueprint));
        setJustSaved(changedLabels(patch));
        setStatus({ kind: "idle" });
        setEditing(false);
      } else if (response.status === 401) {
        setStatus({ kind: "failed", reason: "session_expired" });
      } else if (response.status === 403) {
        setStatus({ kind: "failed", reason: "forbidden" });
      } else if (response.status === 422) {
        const fields = Array.isArray(body?.fields) ? (body.fields as string[]) : [];
        setErrors(
          Object.fromEntries(
            fields.filter((field): field is EditableField => (FIELD_ORDER as string[]).includes(field)).map((field) => [field, SERVER_FIELD_MESSAGE]),
          ),
        );
        setStatus({ kind: "failed", reason: "invalid" });
      } else {
        setStatus({ kind: "failed", reason: "unavailable" });
      }
    } catch {
      setStatus({ kind: "failed", reason: "unavailable" });
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <form
      aria-labelledby={titleId}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className={`mx-auto w-full max-w-[64rem] px-4 pt-3 sm:px-8 sm:pt-6 ${dirty ? "pb-36" : "pb-16"}`}>
        <a
          className="inline-flex min-h-10 items-center gap-1.5 rounded-lg text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:text-hero-navy max-sm:min-h-11"
          href={base}
        >
          <ArrowLeftIcon className="size-4" />
          Ask HeroOS
        </a>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
          <div className="min-w-0">
            <h1
              className="flex flex-wrap items-center gap-3 text-[2rem] font-extrabold leading-tight tracking-[-0.035em] text-hero-navy sm:text-[2.625rem]"
              id={titleId}
            >
              Company Blueprint
              {editing ? (
                <span className="inline-flex h-7 items-center rounded-full bg-hero-blue-tint px-3 text-[0.8125rem] font-bold tracking-normal text-hero-blue-ink">
                  Editing
                </span>
              ) : null}
            </h1>
            <p className="mt-2 text-[1.0625rem] text-hero-muted">
              HeroOS uses this information to tailor HR guidance to {companyName}
              {companyName.endsWith(".") ? "" : "."}
            </p>
          </div>
          {editable ? (
            editing ? (
              dirty ? null : (
                <button className={outlineButton} onClick={discard} type="button">
                  Done
                </button>
              )
            ) : (
              <button className={editButton} id="edit-blueprint" onClick={() => startEditing()} type="button">
                Edit Blueprint
              </button>
            )
          ) : null}
        </div>

        {/* Completeness: one quiet line, never a score. */}
        {editing ? null : (
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.875rem] text-hero-muted">
            {attention.length === 0 ? (
              <span className="inline-flex items-center gap-1.5 font-semibold text-hero-success">
                <CheckCircleIcon className="size-4" />
                Blueprint complete
              </span>
            ) : (
              <Missing>{attention.length === 1 ? "1 detail needs attention" : `${attention.length} details need attention`}</Missing>
            )}
            {saved.updatedAt ? (
              <>
                <span aria-hidden="true" className="max-sm:hidden">
                  ·
                </span>
                <span className="max-sm:basis-full">
                  Last updated <time dateTime={saved.updatedAt}>{formatDay(saved.updatedAt)}</time>
                </span>
              </>
            ) : null}
          </p>
        )}

        <div className="outline-none" ref={statusRef} tabIndex={-1}>
          {justSaved && !editing ? (
            <div className="ws-rise mt-5 flex items-start gap-3 rounded-2xl border border-[#b8dcc6] bg-hero-success-tint px-4 py-3.5 sm:px-5" role="status">
              <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-hero-success" />
              <div className="min-w-0 flex-1">
                <p className="font-bold text-hero-navy">Company Blueprint updated</p>
                <p className="text-[0.9375rem] text-hero-navy/80">{justSaved.join(", ")} saved.</p>
              </div>
              <button
                aria-label="Dismiss"
                className="-my-1 -mr-1 inline-flex size-11 items-center justify-center rounded-full text-hero-muted hover:bg-white/70 sm:size-9"
                onClick={() => setJustSaved(null)}
                type="button"
              >
                <CloseIcon className="size-4" />
              </button>
            </div>
          ) : null}
          {status.kind === "failed" ? (
            <div className="mt-5 rounded-2xl border border-[#f1c2c6] bg-[#fff3f3] px-4 py-3.5 text-[0.9375rem] text-hero-navy sm:px-5" role="alert">
              {FAILURES[status.reason]}
              {status.reason === "session_expired" ? (
                <>
                  {" "}
                  <a className="font-bold text-hero-blue-ink underline" href="/auth/login">
                    Sign in again
                  </a>
                </>
              ) : null}
            </div>
          ) : null}
        </div>

        {!editing && attention.length > 1 ? (
          <nav
            aria-label="Details that need attention"
            className="tone-warning mt-5 rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5 sm:px-5"
          >
            <p className="text-[0.9375rem] text-hero-navy">
              <span className="font-bold">HeroOS gives better guidance with these details.</span>{" "}
              {editable ? <span className="text-hero-navy/75">Add them when you have a minute:</span> : null}
            </p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {attention.map((item) =>
                editable ? (
                  <li key={item.field}>
                    <button
                      className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-(--tone-line) bg-white px-3.5 max-sm:min-h-11 text-[0.875rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-(--tone-chip)"
                      onClick={() => startEditing(item.field)}
                      type="button"
                    >
                      {item.label}
                      <ArrowRightIcon className="size-3.5 text-hero-muted" />
                    </button>
                  </li>
                ) : (
                  <li className="inline-flex min-h-9 items-center rounded-full border border-(--tone-line) bg-white px-3.5 max-sm:min-h-11 text-[0.875rem] font-semibold text-hero-navy" key={item.field}>
                    {item.label}
                  </li>
                ),
              )}
            </ul>
          </nav>
        ) : null}

        <div className={`mt-6 ${sheet}`}>
          {editing ? (
            <EditSheet companyName={companyName} edited={edited} errors={errors} form={form} update={update} />
          ) : (
            <ReadSheet blueprint={saved} companyName={companyName} updated={new Set(justSaved ?? [])} />
          )}
        </div>

        <p className="mt-5 flex gap-2 text-[0.875rem] leading-relaxed text-hero-muted">
          <InfoIcon className="mt-0.5 size-4 shrink-0" />
          Coming next to the Blueprint: your company&apos;s website and summary, policies, HR support and the people who use HeroOS.
        </p>
      </div>

      {dirty ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 px-3 pb-3 sm:px-8 sm:pb-6">
          <div
            aria-label="Unsaved changes"
            className="ws-rise pointer-events-auto mx-auto flex max-w-[64rem] flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border border-hero-navy/10 bg-white/95 px-4 py-3 shadow-[0_24px_50px_-20px_rgb(14_30_61/0.5)] backdrop-blur sm:px-5"
            role="region"
          >
            <p className="min-w-0 flex-1 text-[0.9375rem]">
              <span className="font-bold text-hero-navy">
                {changes.length === 1 ? "1 unsaved change" : `${changes.length || edited.size} unsaved changes`}
              </span>
              {changes.length > 0 ? (
                <span className="text-hero-muted max-sm:block">
                  <span aria-hidden="true" className="max-sm:hidden">
                    {" "}
                    ·{" "}
                  </span>
                  {changes.join(", ")}
                </span>
              ) : null}
            </p>
            <div className="flex items-center gap-2 max-sm:w-full">
              <button className={`${outlineButton} max-sm:flex-1`} disabled={status.kind === "saving"} onClick={discard} type="button">
                Discard
              </button>
              <button
                aria-busy={status.kind === "saving" || undefined}
                className={`${primaryButton} max-sm:flex-1`}
                disabled={status.kind === "saving"}
                type="submit"
              >
                {status.kind === "saving" ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </form>
  );
}
