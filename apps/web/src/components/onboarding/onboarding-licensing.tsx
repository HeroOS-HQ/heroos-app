import type { ReactNode } from "react";

import { BuildingIcon, DocumentIcon, HelpIcon, InfoIcon, MapPinIcon, ScaleIcon } from "@/components/site/icons";
import { APPROVED_LICENSING_AUTHORITIES, LICENSING_OPTIONS, licensingChoiceNote } from "@/lib/onboarding/copy";
import type { FieldErrors, LicensingLocation } from "@/lib/onboarding/model";

import { FieldError, IconRow, OnboardingTextField, RequirementTag } from "./onboarding-field";
import { LicensingAuthorityField } from "./licensing-fields";

/** A lettered group heading (JJ design review, screen 03): "A  Where is your company licensed?". */
export function SectionBar({
  letter,
  id,
  children,
  extra,
}: {
  letter: string;
  id?: string;
  children: ReactNode;
  /** Beside the heading, outside it (e.g. "Required"). */
  extra?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-[#f2f4f9] px-3 py-2">
      <span
        aria-hidden="true"
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-hero-yellow text-[0.9375rem] font-extrabold text-hero-navy"
      >
        {letter}
      </span>
      <h2 className="text-[1.0625rem] font-extrabold text-hero-navy sm:text-lg" id={id}>
        {children}
      </h2>
      {extra}
    </div>
  );
}

const OPTION_ICONS: Record<LicensingLocation, ReactNode> = {
  difc: <BuildingIcon className="size-5" />,
  other: <MapPinIcon className="size-5" />,
  not_sure: <HelpIcon className="size-5" />,
};

const QUESTION = "Where is your company licensed?";

/**
 * Licence & Jurisdiction (screen 03), built only on the registration
 * contract: A) where the business licence was issued, exactly DIFC, Other or
 * "I'm not sure" (required); B) the issuing authority, for Other only and
 * optional; C) how jurisdiction is confirmed. The mockup's licence number,
 * upload and multi-jurisdiction question are not part of registration, so
 * they are not offered. No answer confirms a jurisdiction.
 */
export function OnboardingLicensing({
  location,
  authority,
  onLocationChange,
  onAuthorityChange,
  errors,
}: {
  location: LicensingLocation | "";
  authority: string;
  /** The caller clears the authority whenever the choice changes. */
  onLocationChange: (location: LicensingLocation) => void;
  onAuthorityChange: (authority: string) => void;
  errors: FieldErrors;
}) {
  const errorId = "onboarding-location-error";
  const note = licensingChoiceNote(location);
  return (
    <div className="mt-5 flex flex-col gap-[1.125rem]">
      <section className="flex flex-col gap-3.5">
        <SectionBar extra={<RequirementTag required />} id="onboarding-location-title" letter="A">
          {QUESTION}
        </SectionBar>
        <fieldset
          aria-describedby={errors.licensingLocation ? errorId : "onboarding-location-help"}
          aria-labelledby="onboarding-location-title"
        >
          <p className="sr-only" id="onboarding-location-help">
            Required. Choose the area shown on your business licence, or “I&apos;m not sure”.
          </p>
          {errors.licensingLocation ? <FieldError id={errorId}>{errors.licensingLocation}</FieldError> : null}
          <div className={`grid gap-3 md:grid-cols-3 ${errors.licensingLocation ? "mt-3" : ""}`}>
            {LICENSING_OPTIONS.map((option) => {
              const id = `onboarding-location-${option.value}`;
              return (
                <label
                  className={`relative flex cursor-pointer flex-col rounded-xl border bg-white px-3.5 pb-3 pt-3 transition-colors duration-150 hover:border-hero-blue has-[:checked]:border-2 has-[:checked]:border-hero-blue has-[:checked]:bg-hero-blue-tint has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-3 has-[:focus-visible]:outline-hero-blue ${
                    errors.licensingLocation ? "border-hero-danger" : "border-hero-control"
                  }`}
                  htmlFor={id}
                  key={option.value}
                >
                  <span className="flex items-center gap-2.5">
                    <input
                      aria-describedby={`${id}-description`}
                      checked={location === option.value}
                      className="size-5 shrink-0 accent-hero-blue focus-visible:outline-none"
                      id={id}
                      name="onboarding-location"
                      onChange={() => onLocationChange(option.value)}
                      type="radio"
                      value={option.value}
                    />
                    <span className="text-base font-bold text-hero-navy">{option.label}</span>
                    <span aria-hidden="true" className="ml-auto inline-flex size-8 items-center justify-center rounded-full bg-[#eef1f7] text-hero-navy">
                      {OPTION_ICONS[option.value]}
                    </span>
                  </span>
                  <span className="mt-1.5 block text-[0.8125rem] leading-snug text-hero-muted" id={`${id}-description`}>
                    {option.description}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      </section>

      <section className="flex flex-col gap-3.5">
        <SectionBar letter="B">Issuing authority</SectionBar>
        {location === "other" ? (
          <AuthorityField error={errors.licensingAuthority} onChange={onAuthorityChange} value={authority} />
        ) : (
          <IconRow align="top" icon={<DocumentIcon className="size-6" />}>
            <p className="pt-1 text-[0.9375rem] leading-relaxed text-hero-muted sm:pt-2.5">
              {location === "difc"
                ? "Nothing to add for a DIFC licence."
                : location === "not_sure"
                  ? "Nothing to add for now. You can add your licensing details later in Company Blueprint."
                  : "Only needed if you choose “Other”: you can then enter the authority shown on your licence."}
            </p>
          </IconRow>
        )}
      </section>

      <section className="flex flex-col gap-3.5">
        <SectionBar letter="C">Jurisdiction review</SectionBar>
        <IconRow align="top" icon={<ScaleIcon className="size-6" />}>
          <div
            className={`flex gap-3 rounded-xl border px-4 py-3.5 ${
              location === "not_sure" ? "border-[#f1df8d] bg-hero-yellow-tint" : "border-[#cfe0f8] bg-hero-blue-tint"
            }`}
          >
            <InfoIcon className={`mt-0.5 size-5 shrink-0 ${location === "not_sure" ? "text-hero-navy" : "text-hero-blue"}`} />
            <div className="text-[0.9375rem] leading-relaxed text-hero-navy/85">
              <p className="font-bold text-hero-navy">Jurisdiction is confirmed separately</p>
              {/* The note follows the choice; announced politely when it changes. */}
              <p aria-live="polite" className="mt-0.5">
                {note ??
                  "HeroOS records your answer as you give it and doesn't decide which employment law applies. Until your jurisdiction is confirmed, jurisdiction-specific guidance isn't available."}
              </p>
            </div>
          </div>
        </IconRow>
      </section>
    </div>
  );
}

/** The issuing authority for an "Other" answer: typed until JJ's approved list arrives (then the shared list field). */
function AuthorityField({ value, onChange, error }: { value: string; onChange: (value: string) => void; error?: string }) {
  if (APPROVED_LICENSING_AUTHORITIES !== null) {
    return (
      <IconRow icon={<DocumentIcon className="size-6" />}>
        <LicensingAuthorityField error={error} id="onboarding-authority" onChange={onChange} value={value} />
      </IconRow>
    );
  }
  return (
    <OnboardingTextField
      autoComplete="off"
      error={error}
      hint="Enter the name exactly as it appears on your business licence. You can leave this blank and add it later."
      icon={<DocumentIcon className="size-6" />}
      id="onboarding-authority"
      label="Which authority issued your licence?"
      onChange={onChange}
      placeholder="e.g. the free zone authority named on your licence"
      value={value}
    />
  );
}
