import type { InputHTMLAttributes, Ref } from "react";

import { AlertIcon } from "@/components/site/icons";

import { fieldError, hint as hintClass, input, label as labelClass } from "./styles";

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  error?: string;
  required?: boolean;
  optional?: boolean;
  inputRef?: Ref<HTMLInputElement>;
} & Pick<InputHTMLAttributes<HTMLInputElement>, "autoComplete" | "inputMode" | "maxLength" | "name" | "onBlur" | "disabled">;

/**
 * Labelled text input with an optional hint and an inline error. The hint and
 * error are linked with `aria-describedby`; `aria-invalid` marks the error
 * state, which is also written in words (never colour alone).
 */
export function TextField({ id, label, value, onChange, hint, error, required, optional, inputRef, ...rest }: Props) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        {label}
        {required ? (
          <span className="ml-1 font-semibold text-hero-muted">(required)</span>
        ) : optional ? (
          <span className="ml-1 font-semibold text-hero-muted">(optional)</span>
        ) : null}
      </label>
      {hint ? (
        <span className={hintClass} id={hintId}>
          {hint}
        </span>
      ) : null}
      <input
        {...rest}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        aria-required={required ? true : undefined}
        className={input}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        ref={inputRef}
        type="text"
        value={value}
      />
      {error ? (
        <p className={fieldError} id={errorId}>
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
