"use client";

import { type ReactNode, type Ref, useEffect, useRef, useState } from "react";

import { ArrowLeftIcon, ArrowRightIcon, PencilIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonPrimary, buttonQuiet, buttonSecondary, card, lede, pageTitle } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { licensingLabel } from "@/lib/onboarding/copy";
import {
  buildRegistrationPayload,
  EMPTY_DRAFT,
  type FieldErrors,
  type FieldName,
  LIMITS,
  type LicensingLocation,
  type OnboardingDraft,
  validateCompanyStep,
  validateLicensingStep,
} from "@/lib/onboarding/model";
import {
  readyPath,
  type RegistrationFailure,
  submitRegistration,
} from "@/lib/onboarding/registration-client";

import { LicensingFields } from "./licensing-fields";
import { type StepKey, Stepper } from "./stepper";

/**
 * Founder onboarding (M1-10D): Company details → Licensing → Review, then one
 * registration request. Nothing is saved before "Create my workspace". The
 * draft lives only in this component's memory: never in browser storage.
 *
 * States: ONBOARDING_COMPANY, ONBOARDING_LICENSING, ONBOARDING_REVIEW,
 * REGISTRATION_SUBMITTING, then either navigation to the authoritative
 * "ready" page (REGISTRATION_CREATED / REGISTRATION_EXISTING) or a failure
 * shown on the review step (SESSION_EXPIRED, ACCESS_DENIED,
 * REGISTRATION_DISABLED, validation, API_UNAVAILABLE / uncertain).
 */

type Submission =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "navigating"; destination: string }
  | { status: "failed"; reason: RegistrationFailure };

const COMPANY_FIELDS: FieldName[] = ["companyName", "legalName", "industry", "employeeCount"];
// Element to focus for each field's error (the first radio for the licensing choice).
const FIELD_IDS: Record<FieldName, string> = {
  companyName: "company-name",
  legalName: "legal-name",
  industry: "industry",
  employeeCount: "employee-count",
  licensingLocation: "onboarding-location-difc",
  licensingAuthority: "onboarding-authority",
};
const LICENSING_FIELDS: FieldName[] = ["licensingLocation", "licensingAuthority"];
const SERVER_FIELD_MESSAGE = "HeroOS couldn't accept this value. Please check it and try again.";

type Props = {
  /** Companies the API already lists for this user (from the server page). */
  existingWorkspaces?: { companyId: string; name: string }[];
  /** Test seams; the page uses the defaults. */
  fetcher?: typeof fetch;
  navigate?: (url: string) => void;
};

export function OnboardingWizard({ existingWorkspaces = [], fetcher, navigate }: Props) {
  const [step, setStep] = useState<StepKey>("company");
  const [draft, setDraft] = useState<OnboardingDraft>(EMPTY_DRAFT);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submission, setSubmission] = useState<Submission>({ status: "idle" });
  const inFlight = useRef(false);
  // Set synchronously once the workspace exists: the page may leave at once,
  // before React re-renders and removes the unsaved-details listener.
  const leaving = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  const dirty = JSON.stringify(draft) !== JSON.stringify(EMPTY_DRAFT);
  const busy = submission.status === "submitting" || submission.status === "navigating";

  // After the user changes step: back to the top (the progress indicator is
  // above the card, and focusing alone could leave the heading under the sticky
  // header), then move focus to the new step's heading.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    window.scrollTo({ top: 0, behavior: "instant" });
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  // Ask before leaving with unsaved details (the draft is not stored anywhere).
  // Never once the workspace exists: a "Leave site?" prompt there could cancel
  // the way to it and leave this page locked on "Opening your workspace…".
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!leaving.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (submission.status === "failed") feedbackRef.current?.focus();
  }, [submission]);

  function update<K extends keyof OnboardingDraft>(key: K, value: OnboardingDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    // Clear a shown error as soon as the field is edited.
    const field = key as FieldName;
    if (errors[field]) setErrors((current) => without(current, [field]));
  }

  function chooseLocation(location: LicensingLocation) {
    // A changed choice never keeps a stale authority.
    setDraft((current) => ({
      ...current,
      licensingLocation: location,
      licensingAuthority: location === "other" && current.licensingLocation === "other" ? current.licensingAuthority : "",
    }));
    setErrors((current) => without(current, ["licensingLocation", "licensingAuthority"]));
  }

  function focusFirstError(found: FieldErrors, order: FieldName[]) {
    const first = order.find((field) => found[field]);
    if (first) requestAnimationFrame(() => document.getElementById(FIELD_IDS[first])?.focus());
  }

  function goTo(next: StepKey) {
    setStep(next);
    if (submission.status === "failed") setSubmission({ status: "idle" });
  }

  function continueFromCompany() {
    const found = validateCompanyStep(draft);
    setErrors(found);
    if (Object.keys(found).length > 0) return focusFirstError(found, COMPANY_FIELDS);
    goTo("licensing");
  }

  function continueFromLicensing() {
    const found = validateLicensingStep(draft);
    setErrors(found);
    if (Object.keys(found).length > 0) return focusFirstError(found, LICENSING_FIELDS);
    goTo("review");
  }

  async function createWorkspace() {
    if (inFlight.current) return;
    const built = buildRegistrationPayload(draft);
    if (!built.ok) {
      setErrors(built.errors);
      goTo(Object.keys(built.errors).some((field) => COMPANY_FIELDS.includes(field as FieldName)) ? "company" : "licensing");
      return;
    }
    inFlight.current = true;
    setSubmission({ status: "submitting" });
    const result = await submitRegistration(built.value, fetcher);
    if (result.kind === "success") {
      const destination = readyPath(result.outcome, result.companyId);
      leaving.current = true;
      setSubmission({ status: "navigating", destination });
      (navigate ?? ((url: string) => window.location.assign(url)))(destination);
      return; // Stay locked: the page is leaving (with a link, should it not).
    }
    if (result.reason === "invalid" && result.fields.length > 0) {
      setErrors(Object.fromEntries(result.fields.map((field) => [field, SERVER_FIELD_MESSAGE])));
    }
    setSubmission({ status: "failed", reason: result.reason });
    inFlight.current = false;
  }

  return (
    <div className="mx-auto w-full max-w-[60rem] px-4 pb-16 pt-8 sm:px-6 sm:pb-24 sm:pt-12">
      {existingWorkspaces.length > 0 ? (
        <Notice className="mx-auto mb-6 max-w-[52rem]" title="You already have a HeroOS workspace">
          <p>
            Your account can already open{" "}
            {existingWorkspaces.length === 1 ? (
              <strong>{existingWorkspaces[0].name}</strong>
            ) : (
              `${existingWorkspaces.length} workspaces`
            )}
            .{" "}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load, so the unsaved-draft warning applies */}
            <a className="font-bold text-hero-blue-ink underline underline-offset-4" href="/workspaces">
              Go to my workspace{existingWorkspaces.length === 1 ? "" : "s"}
            </a>
          </p>
        </Notice>
      ) : null}

      <Stepper current={step} />

      <section aria-labelledby="onboarding-heading" className={`${card} mx-auto max-w-[52rem] px-5 py-7 sm:px-10 sm:py-10`}>
        {step === "company" ? (
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              continueFromCompany();
            }}
          >
            <StepHeading headingRef={headingRef} title="Let's set up your company">
              Tell us a little about your business. No HR experience required.
            </StepHeading>
            <div className="mt-8 grid gap-6 md:grid-cols-2">
              <div className="md:col-span-2">
                <TextField
                  autoComplete="organization"
                  error={errors.companyName}
                  hint="The name your team and customers know you by."
                  id="company-name"
                  label="Company name"
                  onChange={(value) => update("companyName", value)}
                  required
                  value={draft.companyName}
                />
              </div>
              <div className="md:col-span-2">
                <TextField
                  autoComplete="off"
                  error={errors.legalName}
                  hint="As shown on your business licence, if it's different."
                  id="legal-name"
                  label="Legal business name"
                  onChange={(value) => update("legalName", value)}
                  optional
                  value={draft.legalName}
                />
              </div>
              <TextField
                autoComplete="off"
                error={errors.industry}
                hint="For example: hospitality, retail, technology."
                id="industry"
                label="Industry"
                onChange={(value) => update("industry", value)}
                optional
                value={draft.industry}
              />
              <TextField
                autoComplete="off"
                error={errors.employeeCount}
                hint={`A whole number, up to ${LIMITS.employeeCountMax.toLocaleString("en-US")}.`}
                id="employee-count"
                inputMode="numeric"
                label="Number of employees"
                onChange={(value) => update("employeeCount", value)}
                optional
                value={draft.employeeCount}
              />
            </div>
            <StepActions>
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load, so the unsaved-draft warning applies */}
              <a className={buttonQuiet} href="/workspaces">
                Cancel
              </a>
              <button className={buttonPrimary} type="submit">
                Continue
                <ArrowRightIcon className="size-4" />
              </button>
            </StepActions>
          </form>
        ) : null}

        {step === "licensing" ? (
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              continueFromLicensing();
            }}
          >
            <StepHeading headingRef={headingRef} title="Where is your company licensed?">
              Choose the location or authority shown on your business licence. This helps HeroOS understand which
              services may apply.
            </StepHeading>
            <div className="mt-8">
              <LicensingFields
                authority={draft.licensingAuthority}
                errors={errors}
                idPrefix="onboarding"
                legend="Where is your company licensed?"
                legendHidden
                location={draft.licensingLocation}
                onAuthorityChange={(value) => update("licensingAuthority", value)}
                onLocationChange={chooseLocation}
              />
            </div>
            <StepActions>
              <button className={buttonSecondary} onClick={() => goTo("company")} type="button">
                <ArrowLeftIcon className="size-4" />
                Back
              </button>
              <button className={buttonPrimary} type="submit">
                Continue
                <ArrowRightIcon className="size-4" />
              </button>
            </StepActions>
          </form>
        ) : null}

        {step === "review" ? (
          <div>
            <StepHeading headingRef={headingRef} title="Review your company details">
              Check everything looks right. Your workspace is created only when you select “Create my workspace”.
            </StepHeading>

            <div className="mt-8 flex flex-col gap-5">
              <ReviewSection disabled={busy} onEdit={() => goTo("company")} title="Company details">
                <ReviewRow label="Company name" value={draft.companyName.trim()} error={errors.companyName} />
                <ReviewRow label="Legal business name" value={draft.legalName.trim()} error={errors.legalName} />
                <ReviewRow label="Industry" value={draft.industry.trim()} error={errors.industry} />
                <ReviewRow label="Number of employees" value={draft.employeeCount.trim()} error={errors.employeeCount} />
              </ReviewSection>
              <ReviewSection disabled={busy} onEdit={() => goTo("licensing")} title="Licensing">
                <ReviewRow
                  label="Licensed in"
                  value={draft.licensingLocation ? licensingLabel(draft.licensingLocation) : ""}
                  error={errors.licensingLocation}
                />
                {draft.licensingLocation === "other" ? (
                  <ReviewRow
                    label="Licensing authority"
                    value={draft.licensingAuthority.trim()}
                    error={errors.licensingAuthority}
                  />
                ) : null}
              </ReviewSection>
              <Notice title="Jurisdiction: not yet confirmed">
                Your licensing details are recorded as you entered them and confirmed separately. Until then,
                jurisdiction-specific guidance isn&apos;t available. You can still use your workspace straight away.
              </Notice>
            </div>

            <div aria-live="polite" className="sr-only">
              {submission.status === "submitting" ? "Creating your workspace…" : null}
              {submission.status === "navigating" ? "Opening your workspace…" : null}
            </div>

            {submission.status === "navigating" ? (
              <p className="mt-6 text-sm text-hero-muted">
                If your workspace doesn&apos;t open in a moment,{" "}
                <a className="font-bold text-hero-blue-ink underline underline-offset-4" href={submission.destination}>
                  open it here
                </a>
                .
              </p>
            ) : null}

            {submission.status === "failed" ? (
              <div className="mt-6" ref={feedbackRef} tabIndex={-1}>
                <RegistrationFeedback
                  onEdit={() => goTo("company")}
                  onRetry={() => void createWorkspace()}
                  reason={submission.reason}
                />
              </div>
            ) : null}

            <StepActions>
              <button className={buttonSecondary} disabled={busy} onClick={() => goTo("licensing")} type="button">
                <ArrowLeftIcon className="size-4" />
                Back
              </button>
              <button
                aria-busy={busy || undefined}
                className={buttonPrimary}
                disabled={busy}
                onClick={() => void createWorkspace()}
                type="button"
              >
                {busy ? <Spinner /> : null}
                {submission.status === "submitting"
                  ? "Creating your workspace…"
                  : submission.status === "navigating"
                    ? "Opening your workspace…"
                    : "Create my workspace"}
              </button>
            </StepActions>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function without(errors: FieldErrors, fields: FieldName[]): FieldErrors {
  return Object.fromEntries(Object.entries(errors).filter(([field]) => !fields.includes(field as FieldName)));
}

function StepHeading({
  title,
  children,
  headingRef,
}: {
  title: string;
  children: ReactNode;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  return (
    <header>
      <h1 className={`${pageTitle} focus-visible:outline-none`} id="onboarding-heading" ref={headingRef} tabIndex={-1}>
        {title}
      </h1>
      <p className={`mt-3 max-w-[40rem] ${lede}`}>{children}</p>
    </header>
  );
}

function StepActions({ children }: { children: ReactNode }) {
  return (
    <div className="mt-10 flex flex-col-reverse gap-3 border-t border-hero-border pt-6 sm:flex-row sm:items-center sm:justify-between">
      {children}
    </div>
  );
}

function ReviewSection({
  title,
  children,
  onEdit,
  disabled,
}: {
  title: string;
  children: ReactNode;
  onEdit: () => void;
  disabled: boolean;
}) {
  return (
    <section aria-label={title} className="rounded-2xl border border-hero-border px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-extrabold text-hero-navy">{title}</h2>
        <button className={buttonQuiet} disabled={disabled} onClick={onEdit} type="button">
          <PencilIcon className="size-4" />
          Edit<span className="sr-only"> {title.toLowerCase()}</span>
        </button>
      </div>
      <dl className="mt-2 divide-y divide-hero-border">{children}</dl>
    </section>
  );
}

function ReviewRow({ label, value, error }: { label: string; value: string; error?: string }) {
  return (
    <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <dt className="text-sm text-hero-muted">{label}</dt>
      <dd className="min-w-0 break-words text-[0.9375rem] font-semibold text-hero-navy sm:max-w-[60%] sm:text-right">
        {value || <span className="font-normal text-hero-muted">Not provided</span>}
        {error ? <span className="mt-1 block text-sm font-semibold text-hero-danger">{error}</span> : null}
      </dd>
    </div>
  );
}

function Spinner() {
  return (
    <svg aria-hidden="true" className="size-5 animate-spin motion-reduce:animate-none" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-90" d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeLinecap="round" strokeWidth="3" />
    </svg>
  );
}

/** Honest, fixed copy for each failure. Never a success message after a failure. */
function RegistrationFeedback({
  reason,
  onRetry,
  onEdit,
}: {
  reason: RegistrationFailure;
  onRetry: () => void;
  onEdit: () => void;
}) {
  switch (reason) {
    case "uncertain":
      return (
        <Notice role="alert" title="We couldn't confirm that your workspace was created" tone="caution">
          <p>
            The connection may have dropped before HeroOS answered. Trying again is safe: it won&apos;t create a second
            workspace for you.
          </p>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
            <button className={buttonQuiet} onClick={onRetry} type="button">
              Try again
            </button>
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load re-reads the API's answer */}
            <a className={buttonQuiet} href="/workspaces">
              Check my workspaces
            </a>
          </div>
        </Notice>
      );
    case "session_expired":
      return (
        <Notice role="alert" title="Your session has ended" tone="caution">
          <p>
            Sign in again to continue. For your security, the details you entered here aren&apos;t stored, so you&apos;ll
            need to enter them again.
          </p>
          <a className={`${buttonQuiet} mt-2`} href="/auth/login">
            Sign in again
          </a>
        </Notice>
      );
    case "refused":
      return (
        <Notice role="alert" title="We couldn't create a workspace for this account" tone="danger">
          <p>
            This can happen when an account has been suspended or its access was removed. Your details weren&apos;t
            saved. If you think this is a mistake, contact HeroOS support.
          </p>
        </Notice>
      );
    case "disabled":
      return (
        <Notice role="alert" title="Workspace setup isn't available yet" tone="caution">
          <p>
            Self-service company setup hasn&apos;t been switched on in this environment yet. Your details weren&apos;t
            saved.
          </p>
        </Notice>
      );
    case "invalid":
      return (
        <Notice role="alert" title="Some details need attention" tone="danger">
          <p>HeroOS couldn&apos;t accept some of the details. Check the highlighted values and try again.</p>
          <button className={`${buttonQuiet} mt-2`} onClick={onEdit} type="button">
            Review company details
          </button>
        </Notice>
      );
    default:
      return (
        <Notice role="alert" title="Something went wrong" tone="danger">
          <p>Your workspace wasn&apos;t created. Please try again; your details are still here.</p>
          <button className={`${buttonQuiet} mt-2`} onClick={onRetry} type="button">
            Try again
          </button>
        </Notice>
      );
  }
}
