import type { ReactNode } from "react";

import {
  AlertIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BookIcon,
  BriefcaseIcon,
  BuildingIcon,
  CheckCircleIcon,
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  DocumentIcon,
  InfoIcon,
  PeopleIcon,
  PlusIcon,
  ScaleIcon,
} from "@/components/site/icons";

import {
  attentionOf,
  type Blueprint,
  BLUEPRINT_STATES,
  type BlueprintState,
  blueprintFor,
  type CompanyUser,
  EDITED_SUMMARY,
  HR_OPTIONS,
} from "./blueprint-scenario";
import { Backdrop, finalHref, Header } from "./final";
import { COMPANY } from "./scenario";

/**
 * Page 2, Company Blueprint: the company context HeroOS uses to tailor its
 * advice. It lives in the same workspace as Ask HeroOS (same header, same
 * light), opened from the account menu. Read first: one sheet, five
 * sections. Edit second: one Edit makes the whole Blueprint editable, and a
 * save bar appears only once something has changed. No mascot.
 */

const BASE = "/design-review/oct20";

export function blueprintHref(state: BlueprintState, clean: boolean, anchor?: string | null) {
  const path = state === "review" ? `${BASE}/blueprint` : `${BASE}/blueprint/${state}`;
  return `${path}${clean ? "?clean=1" : ""}${anchor ? `#${anchor}` : ""}`;
}

/* ------------------------------------------------------------- primitives */

const quietLink =
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg text-[0.875rem] font-bold text-hero-blue-ink underline-offset-4 hover:underline";
const outlineButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-hero-navy/15 bg-white px-4 text-[0.9375rem] font-bold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.05)] transition-colors duration-150 hover:bg-hero-blue-tint";
const primaryButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-hero-navy px-5 text-[0.9375rem] font-bold text-white shadow-[0_10px_20px_-10px_rgb(14_30_61/0.9)] transition-colors duration-150 hover:bg-[#182c55]";
const fieldLabel = "flex items-center gap-2 text-[0.875rem] font-bold text-hero-navy";
const fieldHint = "mt-1 text-[0.8125rem] leading-relaxed text-hero-muted";
const input =
  "mt-1.5 block min-h-12 w-full rounded-xl border border-hero-navy/15 bg-white px-4 text-base text-hero-navy shadow-[inset_0_1px_2px_rgb(14_30_61/0.04)] transition-[border-color,box-shadow] duration-150 placeholder:text-hero-muted/80 focus:border-hero-blue focus:shadow-[0_0_0_4px_rgb(61_107_196/0.12)] focus-visible:outline-none";
const editedInput = "border-hero-blue/60 bg-[#fbfdff]";
const subheading = "text-[0.75rem] font-bold uppercase tracking-[0.1em] text-hero-muted";

/** "Edited" marker: words and a dot, never colour alone. */
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

function Avatar({ user, size = "md" }: { user: CompanyUser; size?: "md" | "lg" }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-extrabold tracking-wide ${
        user.you ? "bg-hero-navy text-white" : "bg-hero-blue-tint text-hero-blue-ink"
      } ${size === "lg" ? "size-11 text-[0.8125rem]" : "size-9 text-[0.75rem]"}`}
    >
      {user.initials}
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
      className="grid scroll-mt-6 gap-x-10 gap-y-3 border-t border-hero-border py-6 first:border-t-0 sm:py-7 md:grid-cols-[15.5rem_minmax(0,1fr)]"
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
      <dd className="min-w-0 text-[0.9375rem] font-semibold leading-relaxed text-hero-navy">{children}</dd>
    </div>
  );
}

/* ------------------------------------------------------------ read view */

function ReadSheet({ blueprint, state, clean }: { blueprint: Blueprint; state: BlueprintState; clean: boolean }) {
  const justSaved = state === "saved";
  const missing = new Set(attentionOf(blueprint).map((item) => item.id));
  const hr = HR_OPTIONS.find((option) => option.value === blueprint.hr);
  const addPolicy = blueprintHref("edit", clean, "policies");

  return (
    <div>
      <Section icon={<BuildingIcon className="size-5" />} id="basics" line="Who you are and what you do." title="Company basics">
        <dl className="divide-y divide-hero-border">
          <Row label="Company name">{blueprint.name}</Row>
          <Row label="Legal company name">{blueprint.legalName}</Row>
          <Row label="Industry">{blueprint.industry}</Row>
          <Row label="Employees">
            {blueprint.employees ?? <span className="font-normal text-hero-muted">Not added</span>}
          </Row>
          <Row label="Company summary" updated={justSaved}>
            {blueprint.summary ? <span className="font-normal">{blueprint.summary}</span> : <Missing />}
          </Row>
        </dl>
      </Section>

      {/* The company's current setting, shown plainly: no badge that could read as a legal verification. */}
      <Section
        attention={missing.has("jurisdiction")}
        icon={<ScaleIcon className="size-5" />}
        id="jurisdiction"
        line="Which employment rules apply to you."
        title="Jurisdiction"
      >
        {missing.has("jurisdiction") ? (
          <>
            <p className="pt-1 text-[1.0625rem]">
              <Missing>Jurisdiction not selected</Missing>
            </p>
            <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
              Until a jurisdiction is set, HeroOS can&apos;t give jurisdiction-specific guidance.
            </p>
          </>
        ) : (
          <>
            <p className="pt-0.5 text-[1.5rem] font-extrabold leading-tight tracking-[-0.02em] text-hero-navy">{blueprint.jurisdiction.label}</p>
            {blueprint.jurisdiction.detail ? <p className="mt-0.5 text-[0.9375rem] text-hero-muted">{blueprint.jurisdiction.detail}</p> : null}
          </>
        )}
      </Section>

      <Section attention={missing.has("policies")} icon={<BookIcon className="size-5" />} id="policies" line="Your handbook and HR policies." title="Policies">
        {blueprint.policies.length > 0 ? (
          <>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.9375rem]">
              <CheckCircleIcon className="size-5 text-hero-success" />
              <span className="font-bold text-hero-navy">{blueprint.policies.length} policies added</span>
              <span className="text-hero-muted max-sm:basis-full max-sm:pl-7">
                <span aria-hidden="true" className="max-sm:hidden">· </span>These help HeroOS tailor advice to your company.
              </span>
            </p>
            <ul className="mt-2 divide-y divide-hero-border">
              {blueprint.policies.map((policy) => (
                <li className="flex items-center gap-3.5 py-2.5" key={policy.name}>
                  <span aria-hidden="true" className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-hero-navy/[0.05] text-hero-navy/70">
                    <DocumentIcon className="size-[1.125rem]" />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-hero-navy">{policy.name}</span>
                    <span className="block text-[0.8125rem] text-hero-muted">{policy.meta}</span>
                  </span>
                </li>
              ))}
            </ul>
            <a className={`${quietLink} mt-1`} href={addPolicy}>
              <PlusIcon className="size-4" />
              Add another policy
            </a>
          </>
        ) : (
          <div className="rounded-2xl border border-dashed border-hero-control/70 bg-[#fbfaf8] px-5 py-4">
            <p className="text-[0.9375rem]">
              <Missing>No policies added yet</Missing>
            </p>
            <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-navy/80">
              Add your employee handbook or HR policies. They help HeroOS tailor advice to how {COMPANY.name} works.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <a className={outlineButton} href={addPolicy}>
                <PlusIcon className="size-5" />
                Add a policy document
              </a>
              <a className={quietLink} href={addPolicy}>
                We don&apos;t have written policies
              </a>
            </div>
          </div>
        )}
      </Section>

      <Section attention={missing.has("hr")} icon={<BriefcaseIcon className="size-5" />} id="hr" line="Who handles HR around the company." title="HR support">
        <dl className="divide-y divide-hero-border">
          <Row label="HR support" updated={justSaved}>
            {hr ? hr.label : <Missing />}
          </Row>
          {blueprint.hrNote ? (
            <Row label="Notes" updated={justSaved}>
              <span className="font-normal">{blueprint.hrNote}</span>
            </Row>
          ) : null}
        </dl>
      </Section>

      <Section icon={<PeopleIcon className="size-5" />} id="people" line="Who HeroOS is talking to." title="People">
        <People blueprint={blueprint} />
      </Section>
    </div>
  );
}

/**
 * The people HeroOS understands as part of the company: the primary contact
 * once, then everyone else who signs in. Names and email identities only; no
 * roles, permissions or invitations (account administration is not Page 2).
 */
function People({ blueprint, editing = false }: { blueprint: Blueprint; editing?: boolean }) {
  const primary = blueprint.users.find((user) => user.primary)!;
  const others = blueprint.users.filter((user) => !user.primary);
  return (
    <>
      {editing ? null : (
        <>
          <h3 className={subheading}>Primary contact</h3>
          <div className="mt-2.5 flex items-start gap-3.5">
            <Avatar size="lg" user={primary} />
            <div className="min-w-0 leading-snug">
              <p className="font-bold text-hero-navy">{primary.name}</p>
              <p className="mt-0.5 text-[0.875rem] text-hero-navy/80">{blueprint.contactTitle}</p>
              <p className="truncate text-[0.875rem] text-hero-muted">{primary.email}</p>
            </div>
          </div>
        </>
      )}
      <h3 className={`${subheading} ${editing ? "mt-6" : "mt-5"}`}>Other people using HeroOS</h3>
      {others.length > 0 ? (
        <ul className="mt-1 divide-y divide-hero-border">
          {others.map((user) => (
            <li className="flex items-center gap-3.5 py-2.5" key={user.email}>
              <Avatar user={user} />
              <span className="min-w-0">
                <span className="block font-semibold text-hero-navy">{user.name}</span>
                <span className="block truncate text-[0.8125rem] text-hero-muted">{user.email}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[0.9375rem] text-hero-muted">No one else at {COMPANY.name} uses HeroOS yet.</p>
      )}
      <p className="mt-2 text-[0.8125rem] text-hero-muted">Each person signs in with their own email.</p>
    </>
  );
}

/* ------------------------------------------------------------ edit view */

function Field({
  id,
  label,
  hint,
  edited = false,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  edited?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="scroll-mt-6" id={`field-${id}`}>
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
    </div>
  );
}

function Choice({
  name,
  value,
  checked,
  title,
  hint,
  children,
}: {
  name: string;
  value: string;
  checked: boolean;
  title: string;
  hint: string;
  children?: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer gap-3 rounded-xl border border-hero-navy/12 bg-white px-4 py-3 transition-colors duration-150 hover:border-hero-blue/50 has-[:checked]:border-hero-blue has-[:checked]:bg-[#f5f8fe] has-[:focus-visible]:shadow-[0_0_0_4px_rgb(61_107_196/0.15)]">
      <input className="mt-1 size-4 shrink-0 accent-hero-navy focus-visible:outline-none" defaultChecked={checked} name={name} type="radio" value={value} />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-hero-navy">{title}</span>
        <span className="block text-[0.8125rem] leading-relaxed text-hero-muted">{hint}</span>
        {children}
      </span>
    </label>
  );
}

function EditSheet({ blueprint, edited }: { blueprint: Blueprint; edited: boolean }) {
  return (
    <div>
      <Section icon={<BuildingIcon className="size-5" />} id="basics" line="Who you are and what you do." title="Company basics">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="bp-name" label="Company name">
            <input className={input} defaultValue={blueprint.name} id="bp-name" type="text" />
          </Field>
          <Field id="bp-legal" label="Legal company name">
            <input className={input} defaultValue={blueprint.legalName} id="bp-legal" type="text" />
          </Field>
          <Field id="bp-industry" label="Industry">
            <input className={input} defaultValue={blueprint.industry} id="bp-industry" type="text" />
          </Field>
          <Field id="bp-employees" label="Employees">
            <input className={input} defaultValue={blueprint.employees ?? ""} id="bp-employees" inputMode="numeric" placeholder="For example: 24" type="text" />
          </Field>
          <div className="sm:col-span-2">
            <Field edited={edited} hint="Briefly describe what your company does and how your team is structured." id="summary" label="Company summary">
              <textarea
                aria-describedby="summary-hint"
                className={`${input} min-h-[7.5rem] resize-y py-3 leading-relaxed ${edited ? editedInput : ""}`}
                defaultValue={edited ? EDITED_SUMMARY : (blueprint.summary ?? "")}
                id="summary"
                placeholder="For example: retail company with three Dubai shops and about 40 employees."
                rows={4}
              />
            </Field>
          </div>
        </div>
      </Section>

      <Section icon={<ScaleIcon className="size-5" />} id="jurisdiction" line="Which employment rules apply to you." title="Jurisdiction">
        <fieldset className="scroll-mt-6" id="field-jurisdiction">
          <legend className={fieldLabel}>Jurisdiction</legend>
          <div className="mt-2 grid gap-2.5">
            <Choice checked={blueprint.jurisdiction.choice === "difc"} hint="Dubai International Financial Centre" name="jurisdiction" title="DIFC" value="difc" />
            <Choice
              checked={blueprint.jurisdiction.choice === "other"}
              hint="Another free zone, or the UAE mainland. Add the authority's name."
              name="jurisdiction"
              title="Another jurisdiction"
              value="other"
            />
            <Choice checked={blueprint.jurisdiction.choice === "not_sure"} hint="You can add it later." name="jurisdiction" title="Not sure yet" value="not_sure" />
          </div>
        </fieldset>
        <p className="mt-3 flex gap-2 text-[0.8125rem] leading-relaxed text-hero-muted">
          <InfoIcon className="mt-0.5 size-4 shrink-0" />
          If you change it, jurisdiction-specific guidance may be unavailable until the new setting is in place.
        </p>
      </Section>

      <Section icon={<BookIcon className="size-5" />} id="policies" line="Your handbook and HR policies." title="Policies">
        <div className="scroll-mt-6" id="field-policies">
          <p className={fieldLabel}>Policy documents</p>
          {blueprint.policies.length > 0 ? (
            <ul className="mt-2 divide-y divide-hero-border rounded-xl border border-hero-navy/12 bg-white">
              {blueprint.policies.map((policy) => (
                <li className="flex items-center gap-3 px-4 py-3" key={policy.name}>
                  <DocumentIcon className="size-5 shrink-0 text-hero-navy/60" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold text-hero-navy">{policy.name}</span>
                    <span className="block text-[0.8125rem] text-hero-muted">{policy.meta}</span>
                  </span>
                  <button aria-label={`Remove ${policy.name}`} className="inline-flex size-10 items-center justify-center rounded-full text-hero-muted hover:bg-hero-navy/[0.05] hover:text-hero-navy" type="button">
                    <CloseIcon className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <button
            className="mt-2.5 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-hero-control/80 bg-[#fbfaf8] px-4 py-4 text-[0.9375rem] font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint"
            type="button"
          >
            <PlusIcon className="size-5" />
            Add a policy document
          </button>
          {blueprint.policies.length === 0 ? (
            <label className="mt-3 flex cursor-pointer items-center gap-2.5 text-[0.9375rem] text-hero-navy">
              <input className="size-4 accent-hero-navy" type="checkbox" />
              We don&apos;t have written policies
            </label>
          ) : null}
        </div>
      </Section>

      <Section icon={<BriefcaseIcon className="size-5" />} id="hr" line="Who handles HR around the company." title="HR support">
        <fieldset className="scroll-mt-6" id="field-hr">
          <legend className={fieldLabel}>
            HR support
            {edited ? <Edited /> : null}
          </legend>
          <div className="mt-2 grid gap-2.5">
            {HR_OPTIONS.map((option) => (
              <Choice checked={(edited ? "external" : blueprint.hr) === option.value} hint={option.hint} key={option.value} name="hr" title={option.label} value={option.value} />
            ))}
          </div>
        </fieldset>
        <div className="mt-4">
          <Field edited={edited} id="hr-note" label="Notes (optional)">
            <input
              className={`${input} ${edited ? editedInput : ""}`}
              defaultValue={edited ? "An outside HR consultant supports us on contracts and policies." : (blueprint.hrNote ?? "")}
              id="hr-note"
              placeholder="For example: the managing partner handles HR matters."
              type="text"
            />
          </Field>
        </div>
      </Section>

      <Section icon={<PeopleIcon className="size-5" />} id="people" line="Who HeroOS is talking to." title="People">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="contact" label="Primary contact">
            <div className="relative">
              <select className={`${input} appearance-none pr-10`} defaultValue={blueprint.users[0].email} id="contact">
                {blueprint.users.map((user) => (
                  <option key={user.email} value={user.email}>
                    {user.name}
                  </option>
                ))}
              </select>
              <ChevronDownIcon className="pointer-events-none absolute right-4 top-1/2 mt-[0.1875rem] size-4 -translate-y-1/2 text-hero-muted" />
            </div>
          </Field>
          <Field id="contact-title" label="Their job title">
            <input className={input} defaultValue={blueprint.contactTitle} id="contact-title" type="text" />
          </Field>
        </div>
        <People blueprint={blueprint} editing />
      </Section>
    </div>
  );
}

/* --------------------------------------------------------------- the page */

export function BlueprintWorkspace({ state, clean }: { state: BlueprintState; clean: boolean }) {
  const blueprint = blueprintFor(state);
  const editing = state === "edit" || state === "unsaved";
  const unsaved = state === "unsaved";
  const attention = editing ? [] : attentionOf(blueprint);
  const review = blueprintHref("review", clean);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <Backdrop quiet />
      <Header caseRef={null} clean={clean} menuCurrent="blueprint" state="empty" />

      <main className="relative z-10 min-h-0 flex-1 overflow-y-auto" id="main">
        <form action={blueprintHref("saved", clean).split("?")[0].split("#")[0]} method="get">
          {clean ? <input name="clean" type="hidden" value="1" /> : null}
          <div className={`mx-auto w-full max-w-[64rem] px-4 pt-3 sm:px-8 sm:pt-6 ${unsaved ? "pb-36" : "pb-16"}`}>
            <a className="inline-flex min-h-10 items-center gap-1.5 rounded-lg text-[0.875rem] font-semibold text-hero-muted transition-colors duration-150 hover:text-hero-navy" href={finalHref("empty", clean)}>
              <ArrowLeftIcon className="size-4" />
              Ask HeroOS
            </a>

            <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
              <div className="min-w-0">
                <h1 className="flex flex-wrap items-center gap-3 text-[2rem] font-extrabold leading-tight tracking-[-0.035em] text-hero-navy sm:text-[2.625rem]">
                  Company Blueprint
                  {editing ? (
                    <span className="inline-flex h-7 items-center rounded-full bg-hero-blue-tint px-3 text-[0.8125rem] font-bold tracking-normal text-hero-blue-ink">
                      Editing
                    </span>
                  ) : null}
                </h1>
                <p className="mt-2 text-[1.0625rem] text-hero-muted">HeroOS uses this information to tailor HR guidance to {COMPANY.name}.</p>
              </div>
              {editing ? (
                unsaved ? null : (
                  <div className="flex items-center gap-2">
                    <a className={outlineButton} href={review}>
                      Done
                    </a>
                  </div>
                )
              ) : (
                <a className={outlineButton} href={blueprintHref("edit", clean)}>
                  Edit Blueprint
                </a>
              )}
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
                  <Missing>
                    {attention.length === 1 ? "1 detail needs attention" : `${attention.length} details need attention`}
                  </Missing>
                )}
                <span aria-hidden="true" className="max-sm:hidden">
                  ·
                </span>
                <span className="max-sm:basis-full">Last updated {blueprint.updated}</span>
              </p>
            )}

            {state === "saved" ? (
              <div className="dr-rise mt-5 flex items-start gap-3 rounded-2xl border border-[#b8dcc6] bg-hero-success-tint px-4 py-3.5 sm:px-5" role="status">
                <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-hero-success" />
                <div className="min-w-0 flex-1">
                  <p className="font-bold text-hero-navy">Company Blueprint updated</p>
                  <p className="text-[0.9375rem] text-hero-navy/80">Company summary and HR support saved. HeroOS will use them in new guidance.</p>
                </div>
                <a aria-label="Dismiss" className="-my-1 -mr-1 inline-flex size-9 items-center justify-center rounded-full text-hero-muted hover:bg-white/70" href={review}>
                  <CloseIcon className="size-4" />
                </a>
              </div>
            ) : null}

            {attention.length > 1 ? (
              <nav aria-label="Details that need attention" className="tone-warning mt-5 rounded-2xl border border-(--tone-line) bg-(--tone-bg) px-4 py-3.5 sm:px-5">
                <p className="text-[0.9375rem] text-hero-navy">
                  <span className="font-bold">HeroOS gives better guidance with these details.</span>{" "}
                  <span className="text-hero-navy/75">Add them when you have a minute:</span>
                </p>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {attention.map((item) => (
                    <li key={item.id}>
                      <a
                        className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-(--tone-line) bg-white px-3.5 text-[0.875rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-(--tone-chip)"
                        href={blueprintHref("edit", clean, item.id)}
                      >
                        {item.label}
                        <ArrowRightIcon className="size-3.5 text-hero-muted" />
                      </a>
                    </li>
                  ))}
                </ul>
              </nav>
            ) : null}

            <div className="mt-6 rounded-[1.75rem] border border-hero-navy/[0.08] bg-white px-5 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_30px_60px_-40px_rgb(14_30_61/0.35)] sm:px-10">
              {editing ? <EditSheet blueprint={blueprint} edited={unsaved} /> : <ReadSheet blueprint={blueprint} clean={clean} state={state} />}
            </div>
          </div>
        </form>
      </main>

      {unsaved ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 px-3 pb-3 sm:px-8 sm:pb-6">
          <div
            aria-label="Unsaved changes"
            className="dr-rise pointer-events-auto mx-auto flex max-w-[64rem] flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border border-hero-navy/10 bg-white/95 px-4 py-3 shadow-[0_24px_50px_-20px_rgb(14_30_61/0.5)] backdrop-blur sm:px-5"
            role="region"
          >
            <p className="min-w-0 flex-1 text-[0.9375rem]">
              <span className="font-bold text-hero-navy">2 unsaved changes</span>
              <span className="text-hero-muted max-sm:block">
                <span aria-hidden="true" className="max-sm:hidden"> · </span>Company summary, HR support
              </span>
            </p>
            <div className="flex items-center gap-2 max-sm:w-full">
              <a className={`${outlineButton} max-sm:flex-1`} href={review}>
                Discard
              </a>
              <a className={`${primaryButton} max-sm:flex-1`} href={blueprintHref("saved", clean)}>
                Save changes
              </a>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** The reviewer's controls (not part of the design). `?clean=1` hides them. */
export function BlueprintReviewBar({ state, clean }: { state: BlueprintState; clean: boolean }) {
  const index = BLUEPRINT_STATES.findIndex((s) => s.key === state);
  const prev = BLUEPRINT_STATES[(index - 1 + BLUEPRINT_STATES.length) % BLUEPRINT_STATES.length];
  const next = BLUEPRINT_STATES[(index + 1) % BLUEPRINT_STATES.length];
  const current = BLUEPRINT_STATES[index];
  const pill = "inline-flex h-7 items-center rounded-full px-2.5 font-bold transition-colors duration-150 hover:bg-white/10";
  return (
    <nav aria-label="Design review controls" className="flex h-11 shrink-0 items-center gap-2 bg-[#0b1730] px-2 text-[0.8125rem] text-white sm:gap-3 sm:px-4">
      <a className="font-extrabold text-white" href={BASE}>
        Page 2 · Company Blueprint
      </a>
      <a className="hidden text-white/60 hover:text-white lg:inline" href={finalHref("empty", false)}>
        Page 1 (approved)
      </a>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        <a aria-label={`Previous state: ${prev.name}`} className={`${pill} px-1.5`} href={blueprintHref(prev.key, clean, prev.anchor)}>
          <ArrowLeftIcon className="size-4" />
        </a>
        <p className="min-w-0 truncate">
          <span className="font-extrabold text-hero-yellow">{current.n}</span> <span className="font-semibold">{current.name}</span>
          <span className="hidden text-white/55 md:inline"> · {current.note}</span>
        </p>
        <a aria-label={`Next state: ${next.name}`} className={`${pill} px-1.5`} href={blueprintHref(next.key, clean, next.anchor)}>
          <ArrowRightIcon className="size-4" />
        </a>
      </div>
      <a className={`${pill} hidden text-white/80 sm:inline-flex`} href={blueprintHref(state, true, current.anchor)}>
        Hide bar
      </a>
    </nav>
  );
}

export function BlueprintScreen({ state, clean }: { state: BlueprintState; clean: boolean }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {clean ? null : <BlueprintReviewBar clean={clean} state={state} />}
      <BlueprintWorkspace clean={clean} state={state} />
    </div>
  );
}
