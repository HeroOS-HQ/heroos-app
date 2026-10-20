"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BriefcaseIcon,
  BuildingIcon,
  CertificateIcon,
  ClockIcon,
  InfoIcon,
  PencilIcon,
  PeopleIcon,
  ScaleIcon,
  StoreIcon,
} from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { buttonQuiet } from "@/components/ui/styles";
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

import { IconRow, OnboardingTextField } from "./onboarding-field";
import {
  ActionBar,
  GuidanceCard,
  onboardingLink,
  OnboardingStage,
  onboardingPrimary,
  onboardingSecondary,
  StageCard,
} from "./onboarding-frame";
import { OnboardingLicensing } from "./onboarding-licensing";
import { OnboardingWelcome } from "./onboarding-welcome";

/**
 * Founder onboarding: the first four of the journey's five stages (JJ design
 * review, screens 01–04). Welcome → Company Basics → Licence & Jurisdiction →
 * Review, then one registration request; the fifth stage, Complete, is the
 * ready page, reached only after the API confirmed it. Welcome is a
 * presentation and sends nothing. Nothing is saved before "Create my
 * workspace". The draft lives only in this component's memory: never in
 * browser storage.
 *
 * States: ONBOARDING_WELCOME, ONBOARDING_COMPANY, ONBOARDING_LICENSING,
 * ONBOARDING_REVIEW, REGISTRATION_SUBMITTING, then either navigation to the
 * authoritative "ready" page (REGISTRATION_CREATED / REGISTRATION_EXISTING)
 * or a failure shown on the review step (SESSION_EXPIRED, ACCESS_DENIED,
 * REGISTRATION_DISABLED, validation, API_UNAVAILABLE / uncertain).
 */

type Stage = "welcome" | "company" | "licensing" | "review";

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
  const [step, setStep] = useState<Stage>("welcome");
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

  function goTo(next: Stage) {
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

  const existingNotice =
    existingWorkspaces.length > 0 ? (
      <Notice title="You already have a HeroOS workspace">
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
    ) : null;

  if (step === "welcome") {
    return <OnboardingWelcome headingRef={headingRef} notice={existingNotice} onStart={() => goTo("company")} />;
  }

  if (step === "company") {
    return (
      <OnboardingStage
        actions={
          <ActionBar
            end={
              <>
                <LeaveSetup />
                <button className={`${onboardingPrimary} sm:min-w-[14.5rem]`} form="onboarding-company-form" type="submit">
                  Continue to Licence
                  <ArrowRightIcon className="size-5 stroke-[2.25]" />
                </button>
              </>
            }
            start={<BackButton onClick={() => goTo("welcome")} />}
          />
        }
        bubble="First, let's set up your company!"
        guidance={
          <GuidanceCard
            items={[
              "Your company name labels your HeroOS workspace.",
              "Only the name is required. The other details are optional.",
              "Nothing is saved until you create your workspace.",
              "You can update the optional details later in Company Blueprint.",
            ]}
            title="Why we need this information"
          />
        }
        notice={existingNotice}
        stage="company"
      >
        <StageCard
          accent="your company"
          headingRef={headingRef}
          intro="Let's start with some basic information about your business. No HR experience required."
          lead="Tell us about"
          stage="company"
        >
          <form
            className="mt-7 flex flex-col gap-[1.375rem]"
            id="onboarding-company-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              continueFromCompany();
            }}
          >
            <OnboardingTextField
              autoComplete="organization"
              error={errors.companyName}
              hint="The name your team and customers know you by."
              icon={<BuildingIcon className="size-6" />}
              id="company-name"
              label="Company name"
              onChange={(value) => update("companyName", value)}
              placeholder="e.g. XYZ Trading"
              required
              value={draft.companyName}
            />
            <OnboardingTextField
              autoComplete="off"
              error={errors.legalName}
              hint="As shown on your business licence, if it's different."
              icon={<StoreIcon className="size-6" />}
              id="legal-name"
              label="Legal business name"
              onChange={(value) => update("legalName", value)}
              placeholder="e.g. XYZ Trading LLC"
              value={draft.legalName}
            />
            <OnboardingTextField
              autoComplete="off"
              error={errors.industry}
              hint="For example: hospitality, retail, construction, technology."
              icon={<BriefcaseIcon className="size-6" />}
              id="industry"
              label="Industry"
              onChange={(value) => update("industry", value)}
              placeholder="e.g. Retail"
              value={draft.industry}
            />
            <OnboardingTextField
              autoComplete="off"
              error={errors.employeeCount}
              hint={`A whole number, up to ${LIMITS.employeeCountMax.toLocaleString("en-US")}.`}
              icon={<PeopleIcon className="size-6" />}
              id="employee-count"
              inputMode="numeric"
              label="Number of employees"
              onChange={(value) => update("employeeCount", value)}
              placeholder="e.g. 25"
              value={draft.employeeCount}
            />
          </form>
        </StageCard>
      </OnboardingStage>
    );
  }

  if (step === "licensing") {
    return (
      <OnboardingStage
        actions={
          <ActionBar
            end={
              <>
                <LeaveSetup />
                <button className={`${onboardingPrimary} sm:min-w-[14.5rem]`} form="onboarding-licensing-form" type="submit">
                  Continue to Review
                  <ArrowRightIcon className="size-5 stroke-[2.25]" />
                </button>
              </>
            }
            start={<BackButton onClick={() => goTo("company")} />}
          />
        }
        bubble="Now, where is your business licensed?"
        guidance={
          <GuidanceCard
            items={[
              "It records where your business licence was issued, as you tell us.",
              "HeroOS doesn't decide which employment law applies from it.",
              "Jurisdiction is confirmed separately before any jurisdiction-specific guidance.",
              "You can update your licensing later in Company Blueprint.",
            ]}
            title="Why this information matters"
          />
        }
        notice={existingNotice}
        stage="licensing"
      >
        <StageCard
          accent="jurisdiction"
          headingRef={headingRef}
          intro="Choose where your business licence was issued. This tells HeroOS which services may apply; it doesn't decide which employment law applies."
          lead="Your licence and"
          stage="licensing"
        >
          <form
            id="onboarding-licensing-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              continueFromLicensing();
            }}
          >
            <OnboardingLicensing
              authority={draft.licensingAuthority}
              errors={errors}
              location={draft.licensingLocation}
              onAuthorityChange={(value) => update("licensingAuthority", value)}
              onLocationChange={chooseLocation}
            />
          </form>
        </StageCard>
      </OnboardingStage>
    );
  }

  return (
    <OnboardingStage
      actions={
        <ActionBar
          end={
            <>
              {busy ? null : <LeaveSetup />}
              <button
                aria-busy={busy || undefined}
                className={`${onboardingPrimary} sm:min-w-[14.5rem]`}
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
                {busy ? null : <ArrowRightIcon className="size-5 stroke-[2.25]" />}
              </button>
            </>
          }
          start={<BackButton disabled={busy} onClick={() => goTo("licensing")} />}
        />
      }
      bubble="Everything look right? Check your details before you continue!"
      guidance={
        <GuidanceCard
          items={[
            "Your workspace is created only when you select “Create my workspace”.",
            "Edit any section: what you've entered stays here as you move between steps.",
            "Jurisdiction stays unconfirmed until it's reviewed separately.",
            "Afterwards, you can update the optional details in Company Blueprint.",
          ]}
          title="Why review before continuing?"
        />
      }
      notice={existingNotice}
      stage="review"
    >
      <StageCard
        accent="company information"
        headingRef={headingRef}
        intro="Here's what you've entered. Edit any section before you create your workspace."
        lead="Review your"
        stage="review"
      >
        <div className="mt-5 flex flex-col gap-3">
          <ReviewSection
            disabled={busy}
            icon={<BuildingIcon className="size-6" />}
            id="review-company"
            onEdit={() => goTo("company")}
            title="Company information"
          >
            <ReviewRow label="Company name" value={draft.companyName.trim()} error={errors.companyName} />
            <ReviewRow label="Legal business name" value={draft.legalName.trim()} error={errors.legalName} />
            <ReviewRow label="Industry" value={draft.industry.trim()} error={errors.industry} />
            <ReviewRow label="Number of employees" value={draft.employeeCount.trim()} error={errors.employeeCount} />
          </ReviewSection>
          <ReviewSection
            disabled={busy}
            icon={<CertificateIcon className="size-6" />}
            id="review-licensing"
            onEdit={() => goTo("licensing")}
            title="Licence details"
          >
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
          <IconRow align="top" icon={<ScaleIcon className="size-6" />}>
            <section aria-labelledby="review-jurisdiction" className="overflow-hidden rounded-xl border border-hero-border">
              <div className="flex min-h-11 items-center bg-[#f2f4f9] px-4 py-1.5">
                <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id="review-jurisdiction">
                  Jurisdiction
                </h2>
              </div>
              <div className="flex gap-3 bg-hero-yellow-tint/50 px-4 py-3">
                <span aria-hidden="true" className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-hero-yellow text-hero-navy">
                  <ClockIcon className="size-5" />
                </span>
                <div className="min-w-0 text-[0.9375rem] leading-relaxed text-hero-navy/85">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <p className="font-bold text-hero-navy">Jurisdiction: not yet confirmed</p>
                    <span className="rounded-full border border-[#f1df8d] bg-white/70 px-2.5 py-0.5 text-[0.8125rem] font-bold text-hero-navy">
                      Not yet confirmed
                    </span>
                  </div>
                  <p className="mt-1">
                    Recorded as you entered it and confirmed separately. Until then, jurisdiction-specific guidance
                    isn&apos;t available; you can still use your workspace.
                  </p>
                </div>
              </div>
            </section>
          </IconRow>
          <div className="flex gap-3 rounded-xl border border-[#cfe0f8] bg-hero-blue-tint px-4 py-3.5">
            <InfoIcon className="mt-0.5 size-5 shrink-0 text-hero-blue" />
            <p className="text-[0.9375rem] leading-relaxed text-hero-navy/85">
              <span className="font-bold text-hero-navy">Please check these details.</span> Nothing is saved until you
              select “Create my workspace”. Afterwards, you can update the optional details and licensing in Company
              Blueprint.
            </p>
          </div>
        </div>

        <div aria-live="polite" className="sr-only">
          {submission.status === "submitting" ? "Creating your workspace…" : null}
          {submission.status === "navigating" ? "Opening your workspace…" : null}
        </div>

        {submission.status === "navigating" ? (
          <p className="mt-5 text-sm text-hero-muted">
            If your workspace doesn&apos;t open in a moment,{" "}
            <a className="font-bold text-hero-blue-ink underline underline-offset-4" href={submission.destination}>
              open it here
            </a>
            .
          </p>
        ) : null}

        {submission.status === "failed" ? (
          <div className="mt-5" ref={feedbackRef} tabIndex={-1}>
            <RegistrationFeedback
              onEdit={() => goTo("company")}
              onRetry={() => void createWorkspace()}
              reason={submission.reason}
            />
          </div>
        ) : null}
      </StageCard>
    </OnboardingStage>
  );
}

function without(errors: FieldErrors, fields: FieldName[]): FieldErrors {
  return Object.fromEntries(Object.entries(errors).filter(([field]) => !fields.includes(field as FieldName)));
}

function BackButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <button className={`${onboardingSecondary} sm:min-w-[10.75rem]`} disabled={disabled} onClick={onClick} type="button">
      <ArrowLeftIcon className="size-5 stroke-[2.25]" />
      Back
    </button>
  );
}

/**
 * Leaving setup (the mockups' "Save and finish later" is not offered: nothing
 * entered here is kept). A full page load, so the browser asks first whenever
 * details have been entered.
 */
function LeaveSetup() {
  return (
    <>
      <p className="hidden text-sm text-hero-muted xl:block">Nothing is saved until you create your workspace.</p>
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load, so the unsaved-draft warning applies */}
      <a className={onboardingSecondary} href="/workspaces">
        Leave setup
      </a>
    </>
  );
}

function ReviewSection({
  id,
  title,
  icon,
  children,
  onEdit,
  disabled,
}: {
  id: string;
  title: string;
  icon: ReactNode;
  children: ReactNode;
  onEdit: () => void;
  disabled: boolean;
}) {
  return (
    <IconRow align="top" icon={icon}>
      <section aria-labelledby={id} className="@container overflow-hidden rounded-xl border border-hero-border">
        <div className="flex items-center justify-between gap-3 bg-[#f2f4f9] py-0.5 pl-4 pr-2">
          <h2 className="text-[1.0625rem] font-extrabold text-hero-navy" id={id}>
            {title}
          </h2>
          <button className={onboardingLink} disabled={disabled} onClick={onEdit} type="button">
            <PencilIcon className="size-4" />
            {"Edit "}
            <span className="sr-only">{title.toLowerCase()}</span>
          </button>
        </div>
        <dl className="grid gap-x-6 gap-y-1.5 px-4 py-3 @[40rem]:grid-cols-2">{children}</dl>
      </section>
    </IconRow>
  );
}

function ReviewRow({ label, value, error }: { label: string; value: string; error?: string }) {
  return (
    <div className="grid min-w-0 gap-0.5 min-[480px]:grid-cols-[minmax(0,9.25rem)_minmax(0,1fr)] min-[480px]:gap-3">
      <dt className="text-sm leading-6 text-hero-muted">{label}</dt>
      <dd className="min-w-0 break-words text-[0.9375rem] font-semibold leading-6 text-hero-navy">
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
