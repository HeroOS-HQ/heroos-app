import { AlertIcon } from "@/components/site/icons";
import { Notice } from "@/components/ui/notice";
import { fieldError, hint as hintClass, input, label as labelClass } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { APPROVED_LICENSING_AUTHORITIES, LICENSING_OPTIONS, licensingChoiceNote } from "@/lib/onboarding/copy";
import type { FieldErrors, LicensingLocation } from "@/lib/onboarding/model";

type Props = {
  idPrefix: string;
  legend: string;
  /** Hide the legend visually when a page heading already asks the question. */
  legendHidden?: boolean;
  location: LicensingLocation | "";
  authority: string;
  /** The caller clears the authority whenever the choice changes. */
  onLocationChange: (location: LicensingLocation) => void;
  onAuthorityChange: (authority: string) => void;
  errors: FieldErrors;
};

/**
 * "Where is your company licensed?" (JJ, 13 October): DIFC, Other (with the
 * issuing authority) or "I'm not sure". Native radio buttons in large cards,
 * grouped by a fieldset. The answer is recorded as the customer's statement:
 * no choice confirms a jurisdiction, and there are no follow-up questions.
 */
export function LicensingFields({
  idPrefix,
  legend,
  legendHidden,
  location,
  authority,
  onLocationChange,
  onAuthorityChange,
  errors,
}: Props) {
  const errorId = `${idPrefix}-location-error`;
  const note = licensingChoiceNote(location);
  return (
    <div className="flex flex-col gap-6">
      <fieldset aria-describedby={errors.licensingLocation ? errorId : undefined}>
        <legend className={legendHidden ? "sr-only" : `${labelClass} mb-3`}>{legend}</legend>
        {errors.licensingLocation ? (
          <p className={`${fieldError} mb-3 mt-0`} id={errorId}>
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>
              <span className="sr-only">Error: </span>
              {errors.licensingLocation}
            </span>
          </p>
        ) : null}
        <div className="grid gap-3 md:grid-cols-3">
          {LICENSING_OPTIONS.map((option) => {
            const id = `${idPrefix}-location-${option.value}`;
            return (
              <label
                className={`group relative flex min-h-[5.5rem] cursor-pointer items-start gap-3 rounded-2xl border bg-white p-4 transition-colors duration-150 hover:border-hero-blue has-[:checked]:border-2 has-[:checked]:border-hero-blue has-[:checked]:bg-hero-blue-tint has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-3 has-[:focus-visible]:outline-hero-blue ${
                  errors.licensingLocation ? "border-hero-danger" : "border-hero-control"
                }`}
                htmlFor={id}
                key={option.value}
              >
                <input
                  aria-describedby={`${id}-description`}
                  checked={location === option.value}
                  className="mt-1 size-5 shrink-0 accent-hero-blue focus-visible:outline-none"
                  id={id}
                  name={`${idPrefix}-location`}
                  onChange={() => onLocationChange(option.value)}
                  type="radio"
                  value={option.value}
                />
                <span className="min-w-0">
                  <span className="block text-base font-bold text-hero-navy">{option.label}</span>
                  <span className="mt-1 block text-sm leading-relaxed text-hero-muted" id={`${id}-description`}>
                    {option.description}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {location === "other" ? (
        <LicensingAuthorityField
          error={errors.licensingAuthority}
          id={`${idPrefix}-authority`}
          onChange={onAuthorityChange}
          value={authority}
        />
      ) : null}

      <div aria-live="polite">{note ? <Notice tone={location === "not_sure" ? "caution" : "info"}>{note}</Notice> : null}</div>
    </div>
  );
}

/**
 * The issuing authority for an "Other" answer. JJ's approved list is pending
 * (`APPROVED_LICENSING_AUTHORITIES` is null), so the customer types the name;
 * HeroOS records it and never interprets it. When the list arrives, the same
 * field becomes a select with a typed "not listed" fallback.
 */
export function LicensingAuthorityField({
  id,
  value,
  onChange,
  error,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  const catalog = APPROVED_LICENSING_AUTHORITIES;
  if (catalog === null) {
    return (
      <TextField
        autoComplete="off"
        error={error}
        hint="Enter the name exactly as it appears on your business licence. You can leave this blank and add it later."
        id={id}
        label="Which authority issued your licence?"
        onChange={onChange}
        optional
        value={value}
      />
    );
  }
  // Catalog mode (not active until JJ provides the list).
  const listed = catalog.some((option) => option.label === value);
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        Which authority issued your licence? <span className="ml-1 font-semibold text-hero-muted">(optional)</span>
      </label>
      <span className={hintClass}>Choose the authority shown on your business licence.</span>
      <select
        className={input}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={listed ? value : ""}
      >
        <option value="">Select an authority</option>
        {catalog.map((option) => (
          <option key={option.value} value={option.label}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
