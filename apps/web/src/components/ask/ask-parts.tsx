"use client";

import type { FormEvent, ReactNode } from "react";

import { AdviserMark } from "@/components/app/workspace-chrome";
import { SendIcon } from "@/components/site/icons";

/** Pieces of Page 1, Ask HeroOS (approved Oct 20 design), shared by both ways it answers. */

/** The approved landing: the mark, the welcome, the question, then the composer below it. */
export function AskLanding({ returning, children }: { returning: boolean; children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col px-4 pb-4 sm:items-center sm:justify-center sm:px-6 sm:pb-[12vh]">
      <div className="flex flex-1 flex-col items-center justify-center text-center sm:flex-none">
        <span className="ws-rise">
          <AdviserMark size="hero" />
        </span>
        <p className="ws-rise mt-6 text-[0.9375rem] font-semibold text-hero-muted sm:text-base">
          {returning ? "Welcome back." : "Welcome."}
        </p>
        <h1 className="ws-rise mt-2 text-[2.375rem] font-extrabold leading-[1.04] tracking-[-0.04em] text-hero-navy sm:text-[3.5rem]">
          What can HR do for you today?
        </h1>
        <p className="ws-rise-late mt-4 text-[1.0625rem] text-hero-muted sm:text-xl">Explain the situation in your own words.</p>
      </div>
      <div className="w-full sm:mt-11 sm:max-w-[46rem]">{children}</div>
    </div>
  );
}

/**
 * The one box: free text, Enter adds a line, Ctrl+Enter (⌘+Enter) or the
 * button sends. `compact`: docked under a conversation.
 */
export function Composer({
  value,
  onChange,
  onSend,
  canSend,
  disabled = false,
  readOnly = false,
  maxLength,
  placeholder,
  describedBy,
  compact = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  canSend: boolean;
  disabled?: boolean;
  readOnly?: boolean;
  maxLength: number;
  placeholder: string;
  describedBy?: string;
  compact?: boolean;
}) {
  return (
    <form
      noValidate
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onSend();
      }}
    >
      <div
        className={`rounded-[1.75rem] border border-hero-navy/[0.12] bg-white shadow-[0_1px_2px_rgb(14_30_61/0.05),0_28px_60px_-30px_rgb(14_30_61/0.45)] transition-[border-color,box-shadow] duration-200 focus-within:border-hero-blue focus-within:shadow-[0_0_0_4px_rgb(61_107_196/0.12),0_28px_60px_-30px_rgb(14_30_61/0.45)] ${
          disabled ? "opacity-70" : ""
        }`}
      >
        <label className="sr-only" htmlFor="ask-heroos">
          Explain the situation in your own words
        </label>
        {/* The composer's rounded border shows focus (focus-within); the field draws no
            rectangle of its own. `!`: the global :focus-visible outline is unlayered, so it
            outranks utilities. In forced-colors mode the field keeps an outline. */}
        <textarea
          aria-describedby={describedBy}
          className={`block w-full resize-none bg-transparent px-6 pt-5 text-[1.0625rem] leading-relaxed text-hero-navy placeholder:text-hero-muted/80 focus-visible:outline-hidden! disabled:cursor-not-allowed sm:text-lg ${
            compact ? "min-h-[4.5rem] sm:min-h-[4.75rem]" : "min-h-[7rem] sm:min-h-[7.75rem]"
          }`}
          disabled={disabled}
          id="ask-heroos"
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            // Enter adds a line; Ctrl+Enter (⌘+Enter) sends.
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onSend();
          }}
          placeholder={placeholder}
          readOnly={readOnly}
          rows={compact ? 2 : 3}
          value={value}
        />
        <div className="flex items-center gap-2 px-3 pb-3">
          <button
            aria-label="Send"
            className={`ml-auto inline-flex size-12 shrink-0 items-center justify-center rounded-full text-white transition-[background-color,transform] duration-150 ${
              canSend
                ? "bg-hero-navy shadow-[0_10px_20px_-10px_rgb(14_30_61/0.9)] hover:-translate-y-px hover:bg-[#182c55]"
                : "cursor-not-allowed bg-[#c5ccd9]"
            }`}
            disabled={!canSend}
            type="submit"
          >
            <SendIcon className="size-5" />
          </button>
        </div>
      </div>
    </form>
  );
}

/** A problem with the last send, in words, below the box. */
export function AskAlert({ children }: { children: ReactNode }) {
  return (
    <div
      className="ws-rise mt-3 rounded-2xl border border-[#f1c2c6] bg-[#fff3f3] px-4 py-3 text-left text-[0.9375rem] text-hero-navy"
      id="ask-status"
      role="alert"
    >
      {children}
    </div>
  );
}

export function SignInAgain() {
  return (
    <>
      {" "}
      <a className="font-bold text-hero-blue-ink underline" href="/auth/login">
        Sign in again
      </a>
    </>
  );
}
