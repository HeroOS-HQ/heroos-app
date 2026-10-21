import { BookIcon, DocumentIcon, MonitorIcon } from "@/components/site/icons";
import { POLICIES_OPTIONS, SUMMARY_HELP } from "@/lib/blueprint/model";
import { type FieldErrors, LIMITS, type OnboardingDraft, type PoliciesExist } from "@/lib/onboarding/model";

import { FieldError, IconRow, OnboardingTextArea, OnboardingTextField, RequirementTag } from "./onboarding-field";

/**
 * About Your Company (M2-NEW-03): the first company context for the Company
 * Blueprint, every answer optional. The website (stored as an address only:
 * HeroOS never visits it), a short summary, and whether HR policies already
 * exist. The same validation as the Blueprint page; the longer details
 * (policy notes, HR support, people) are left for the Blueprint.
 */
export function OnboardingContext({
  draft,
  errors,
  update,
}: {
  draft: Pick<OnboardingDraft, "websiteUrl" | "companySummary" | "policiesExist">;
  errors: FieldErrors;
  update: <K extends "websiteUrl" | "companySummary" | "policiesExist">(key: K, value: OnboardingDraft[K]) => void;
}) {
  const errorId = "onboarding-policies-error";
  return (
    <div className="mt-7 flex flex-col gap-[1.375rem]">
      <OnboardingTextField
        autoComplete="url"
        error={errors.websiteUrl}
        hint="HeroOS keeps the address only. It doesn't visit or read your website."
        icon={<MonitorIcon className="size-6" />}
        id="website-url"
        inputMode="url"
        label="Company website"
        onChange={(value) => update("websiteUrl", value)}
        placeholder="e.g. www.xyztrading.ae"
        value={draft.websiteUrl}
      />
      <OnboardingTextArea
        error={errors.companySummary}
        hint={SUMMARY_HELP}
        icon={<DocumentIcon className="size-6" />}
        id="company-summary"
        label="Company summary"
        maxLength={LIMITS.companySummary + 200}
        onChange={(value) => update("companySummary", value)}
        placeholder="e.g. We run two cafés in Dubai. A general manager leads 18 staff across both sites."
        value={draft.companySummary}
      />
      <IconRow align="top" icon={<BookIcon className="size-6" />}>
        <fieldset aria-describedby={errors.policiesExist ? errorId : "onboarding-policies-help"}>
          <legend className="text-base font-bold text-hero-navy">
            Does your company already have HR policies?
            <RequirementTag />
          </legend>
          <p className="mt-1 text-sm leading-relaxed text-hero-muted" id="onboarding-policies-help">
            For example, an employee handbook or a disciplinary policy. You can add details later in Company Blueprint.
          </p>
          {errors.policiesExist ? <FieldError id={errorId}>{errors.policiesExist}</FieldError> : null}
          <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
            {POLICIES_OPTIONS.map((option) => {
              const id = `onboarding-policies-${option.value.replace("_", "-")}`;
              return (
                <label
                  className="relative flex min-h-11 cursor-pointer items-center gap-2.5 rounded-xl border border-hero-control bg-white px-3.5 py-2.5 transition-colors duration-150 hover:border-hero-blue has-[:checked]:border-2 has-[:checked]:border-hero-blue has-[:checked]:bg-hero-blue-tint has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-3 has-[:focus-visible]:outline-hero-blue"
                  htmlFor={id}
                  key={option.value}
                >
                  <input
                    checked={draft.policiesExist === option.value}
                    className="size-5 shrink-0 accent-hero-blue focus-visible:outline-none"
                    id={id}
                    name="onboarding-policies"
                    onChange={() => update("policiesExist", option.value as PoliciesExist)}
                    type="radio"
                    value={option.value}
                  />
                  <span className="text-base font-bold text-hero-navy">{option.title}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
      </IconRow>
    </div>
  );
}
