"use client";

import { useEffect, useRef, useState } from "react";

import { LicensingFields } from "@/components/onboarding/licensing-fields";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, card, sectionTitle } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { JurisdictionStatus } from "@/components/workspace/jurisdiction-status";
import {
  type BlueprintPatch,
  checkEmployeeCount,
  checkText,
  type FieldErrors,
  type FieldName,
  LIMITS,
  type LicensingLocation,
  licensingPayload,
} from "@/lib/onboarding/model";
import type { Blueprint } from "@/lib/server/heroos-api";

/**
 * PROFILE_EDITABLE: a Company administrator edits the Blueprint fields the
 * M1-10C API allows. Only changed fields are sent (PATCH), "Saved" appears only
 * after the API confirms, and the view is refreshed from the API's answer
 * (jurisdiction readiness may change with the licensing answer). The API
 * enforces the administrator role on every save, whatever this form shows.
 */

type Form = {
  legalName: string;
  industry: string;
  employeeCount: string;
  licensingLocation: LicensingLocation | "";
  licensingAuthority: string;
};

type Status =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "unchanged" }
  | { kind: "failed"; reason: "session_expired" | "forbidden" | "invalid" | "unavailable" };

function formFrom(blueprint: Blueprint): Form {
  return {
    legalName: blueprint.legalName ?? "",
    industry: blueprint.industry ?? "",
    employeeCount: blueprint.employeeCount === null ? "" : String(blueprint.employeeCount),
    licensingLocation: blueprint.licensing.location ?? "",
    licensingAuthority: blueprint.licensing.authority ?? "",
  };
}

/** Validate the form and build a patch of the changed fields only. */
export function buildPatch(form: Form, saved: Blueprint): { patch: BlueprintPatch; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const patch: BlueprintPatch = {};
  const legal = checkText(form.legalName, LIMITS.legalName);
  if (legal.error) errors.legalName = legal.error;
  else if (legal.value !== saved.legalName) patch.legal_name = legal.value;
  const industry = checkText(form.industry, LIMITS.industry);
  if (industry.error) errors.industry = industry.error;
  else if (industry.value !== saved.industry) patch.industry = industry.value;
  const count = checkEmployeeCount(form.employeeCount);
  if (count.error) errors.employeeCount = count.error;
  else if (count.value !== saved.employeeCount) patch.employee_count = count.value;
  if (form.licensingLocation !== "") {
    const authority = checkText(form.licensingAuthority, LIMITS.licensingAuthority);
    if (form.licensingLocation === "other" && authority.error) {
      errors.licensingAuthority = authority.error;
    } else {
      const next = licensingPayload(form.licensingLocation, form.licensingAuthority);
      if (next.location !== saved.licensing.location || (next.authority ?? null) !== saved.licensing.authority) {
        patch.licensing = next;
      }
    }
  }
  return { patch, errors };
}

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

const SERVER_FIELD_MESSAGE = "HeroOS couldn't accept this value. Please check it and try again.";
const ORDER: FieldName[] = ["legalName", "industry", "employeeCount", "licensingLocation", "licensingAuthority"];
const FIELD_IDS: Partial<Record<FieldName, string>> = {
  legalName: "settings-legal-name",
  industry: "settings-industry",
  employeeCount: "settings-employee-count",
  licensingLocation: "settings-location-difc",
  licensingAuthority: "settings-authority",
};

export function CompanySettingsForm({
  companyId,
  companyName,
  initial,
  fetcher,
}: {
  companyId: string;
  companyName: string;
  initial: Blueprint;
  fetcher?: typeof fetch;
}) {
  const [saved, setSaved] = useState(initial);
  const [form, setForm] = useState<Form>(() => formFrom(initial));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const inFlight = useRef(false);
  const statusRef = useRef<HTMLDivElement>(null);

  const pending = buildPatch(form, saved);
  const dirty = Object.keys(pending.patch).length > 0;
  const licensingChanging = pending.patch.licensing !== undefined;
  const hasConfirmation = saved.jurisdiction.readiness !== "unconfirmed";

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (status.kind === "saved" || status.kind === "failed" || status.kind === "unchanged") statusRef.current?.focus();
  }, [status]);

  function update<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => Object.fromEntries(Object.entries(current).filter(([field]) => field !== key)));
    if (status.kind !== "saving") setStatus({ kind: "idle" });
  }

  async function save() {
    if (inFlight.current) return;
    const { patch, errors: found } = buildPatch(form, saved);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      const first = ORDER.find((field) => found[field]);
      const id = first ? FIELD_IDS[first] : undefined;
      if (id) requestAnimationFrame(() => document.getElementById(id)?.focus());
      return;
    }
    if (Object.keys(patch).length === 0) {
      setStatus({ kind: "unchanged" });
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
        setStatus({ kind: "saved" });
      } else if (response.status === 401) {
        setStatus({ kind: "failed", reason: "session_expired" });
      } else if (response.status === 403) {
        setStatus({ kind: "failed", reason: "forbidden" });
      } else if (response.status === 422) {
        const fields = Array.isArray(body?.fields) ? (body.fields as FieldName[]) : [];
        setErrors(Object.fromEntries(fields.filter((field) => ORDER.includes(field)).map((field) => [field, SERVER_FIELD_MESSAGE])));
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
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <section aria-labelledby="details-heading" className={`${card} p-5 sm:p-8`}>
        <h2 className={sectionTitle} id="details-heading">
          Company details
        </h2>
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="md:col-span-2">
            <p className="block text-[0.9375rem] font-bold text-hero-navy">Company name</p>
            <p className="mt-2 break-words text-base text-hero-navy">{companyName}</p>
            <p className="mt-1 text-sm text-hero-muted">The workspace name can&apos;t be changed here yet.</p>
          </div>
          <div className="md:col-span-2">
            <TextField
              autoComplete="off"
              error={errors.legalName}
              hint="As shown on your business licence."
              id="settings-legal-name"
              label="Legal business name"
              onChange={(value) => update("legalName", value)}
              optional
              value={form.legalName}
            />
          </div>
          <TextField
            autoComplete="off"
            error={errors.industry}
            id="settings-industry"
            label="Industry"
            onChange={(value) => update("industry", value)}
            optional
            value={form.industry}
          />
          <TextField
            autoComplete="off"
            error={errors.employeeCount}
            hint="A whole number."
            id="settings-employee-count"
            inputMode="numeric"
            label="Number of employees"
            onChange={(value) => update("employeeCount", value)}
            optional
            value={form.employeeCount}
          />
        </div>
      </section>

      <section aria-labelledby="licensing-heading" className={`${card} p-5 sm:p-8`}>
        <h2 className={sectionTitle} id="licensing-heading">
          Licensing
        </h2>
        <p className="mt-1 text-[0.9375rem] text-hero-muted">Where your business licence was issued.</p>
        <div className="mt-6">
          <LicensingFields
            authority={form.licensingAuthority}
            errors={errors}
            idPrefix="settings"
            legend="Where is your company licensed?"
            location={form.licensingLocation}
            onAuthorityChange={(value) => update("licensingAuthority", value)}
            onLocationChange={(location) =>
              setForm((current) => ({
                ...current,
                licensingLocation: location,
                licensingAuthority:
                  location === "other" && current.licensingLocation === "other" ? current.licensingAuthority : "",
              }))
            }
          />
        </div>
        {licensingChanging && hasConfirmation ? (
          <Notice className="mt-5" title="Your jurisdiction will need to be confirmed again" tone="caution">
            Your current jurisdiction was confirmed for the licensing details on record. If you save a change, it
            goes back to “not yet confirmed” until it&apos;s reviewed again.
          </Notice>
        ) : null}
        <div className="mt-6">
          <JurisdictionStatus jurisdiction={saved.jurisdiction} />
        </div>
      </section>

      <div ref={statusRef} tabIndex={-1}>
        <SaveStatus status={status} />
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <a className={buttonQuiet} href={`/workspaces/${encodeURIComponent(companyId)}`}>
          Back to workspace
        </a>
        <button aria-busy={status.kind === "saving" || undefined} className={buttonPrimary} disabled={status.kind === "saving"} type="submit">
          {status.kind === "saving" ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function SaveStatus({ status }: { status: Status }) {
  switch (status.kind) {
    case "saved":
      return (
        <Notice role="status" title="Changes saved" tone="success">
          Your company details are up to date.
        </Notice>
      );
    case "unchanged":
      return (
        <Notice role="status" title="No changes to save">
          Edit a field first, then save.
        </Notice>
      );
    case "failed":
      return status.reason === "session_expired" ? (
        <Notice role="alert" title="Your session has ended" tone="caution">
          <p>Your changes weren&apos;t saved. Sign in again to continue.</p>
          <a className={`${buttonQuiet} mt-1`} href="/auth/login">
            Sign in again
          </a>
        </Notice>
      ) : status.reason === "forbidden" ? (
        <Notice role="alert" title="You can't change these details" tone="danger">
          Your changes weren&apos;t saved. Only company administrators can edit company details, and your access may
          have changed.
        </Notice>
      ) : status.reason === "invalid" ? (
        <Notice role="alert" title="Some details need attention" tone="danger">
          Your changes weren&apos;t saved. Check the highlighted fields and try again.
        </Notice>
      ) : (
        <Notice role="alert" title="We couldn't save your changes" tone="danger">
          HeroOS didn&apos;t confirm the update. Please try again.
        </Notice>
      );
    default:
      return null;
  }
}
