import type { InputHTMLAttributes, ReactNode } from "react";

import { AlertIcon } from "@/components/site/icons";

/** The journey's text input (JJ design review, screen 02): roomy, rounded, blue when focused, red with an error. */
export const onboardingInput =
  "mt-1.5 block min-h-11 w-full rounded-[0.625rem] border border-hero-control bg-white px-3.5 py-2 text-base text-hero-navy transition-colors duration-150 placeholder:text-[#6b7588] focus:border-hero-blue aria-[invalid=true]:border-2 aria-[invalid=true]:border-hero-danger";

/** A light circle holding a field's icon, left of the field (hidden on the narrowest phones). */
export function FieldIcon({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`hidden size-11 shrink-0 items-center justify-center rounded-full bg-[#eef1f7] text-hero-navy min-[400px]:inline-flex sm:size-14 ${className ?? ""}`}
    >
      {children}
    </span>
  );
}

/** An icon beside its content: the rows of the journey's forms and review. */
export function IconRow({ icon, children, align = "field" }: { icon: ReactNode; children: ReactNode; align?: "field" | "top" }) {
  return (
    <div className="flex items-start gap-3 sm:gap-[1.625rem]">
      <FieldIcon className={align === "field" ? "mt-1.5" : ""}>{icon}</FieldIcon>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/** "Required" or "Optional" beside a label, in words (never colour alone). */
export function RequirementTag({ required }: { required?: boolean }) {
  return required ? (
    <span className="ml-2.5 text-sm font-semibold text-hero-danger">
      <span aria-hidden="true">*</span>Required
    </span>
  ) : (
    <span className="ml-2.5 text-sm font-medium text-hero-muted">Optional</span>
  );
}

/** A field error in words, linked to its control by `aria-describedby`. */
export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p className="mt-1.5 flex items-start gap-1.5 text-sm font-semibold text-hero-danger" id={id}>
      <AlertIcon className="mt-0.5 size-4 shrink-0" />
      <span>
        <span className="sr-only">Error: </span>
        {children}
      </span>
    </p>
  );
}

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  icon: ReactNode;
  hint?: string;
  error?: string;
  required?: boolean;
  placeholder?: string;
} & Pick<InputHTMLAttributes<HTMLInputElement>, "autoComplete" | "inputMode" | "disabled">;

/**
 * Labelled text input in an icon row: label and requirement, the input, then
 * its error and hint (both linked with `aria-describedby`; `aria-invalid`
 * marks the error, which is also written in words).
 */
export function OnboardingTextField({ id, label, value, onChange, icon, hint, error, required, placeholder, ...rest }: Props) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <IconRow icon={icon}>
      <label className="block text-base font-bold text-hero-navy" htmlFor={id}>
        {label}
        <RequirementTag required={required} />
      </label>
      <input
        {...rest}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        aria-required={required ? true : undefined}
        className={onboardingInput}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        type="text"
        value={value}
      />
      {error && errorId ? <FieldError id={errorId}>{error}</FieldError> : null}
      {hint ? (
        <span className="mt-1.5 block text-sm leading-relaxed text-hero-muted" id={hintId}>
          {hint}
        </span>
      ) : null}
    </IconRow>
  );
}

/**
 * Labelled multi-line text in an icon row (the company summary): like
 * `OnboardingTextField`, with line breaks kept.
 */
export function OnboardingTextArea({
  id,
  label,
  value,
  onChange,
  icon,
  hint,
  error,
  placeholder,
  maxLength,
}: Omit<Props, "required" | "autoComplete" | "inputMode" | "disabled"> & { maxLength?: number }) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <IconRow icon={icon}>
      <label className="block text-base font-bold text-hero-navy" htmlFor={id}>
        {label}
        <RequirementTag />
      </label>
      <textarea
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        className={`${onboardingInput} min-h-28 resize-y py-2.5 leading-relaxed`}
        id={id}
        maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={4}
        value={value}
      />
      {error && errorId ? <FieldError id={errorId}>{error}</FieldError> : null}
      {hint ? (
        <span className="mt-1.5 block text-sm leading-relaxed text-hero-muted" id={hintId}>
          {hint}
        </span>
      ) : null}
    </IconRow>
  );
}
