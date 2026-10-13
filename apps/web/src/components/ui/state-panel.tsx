import type { ReactNode } from "react";

import { card, lede, pageTitle } from "./styles";

/**
 * A full-page state (welcome, no access, session ended, service unavailable):
 * one heading, plain-English explanation, and the next actions. Text is fixed
 * copy chosen by state; nothing from an API or provider error is shown.
 */
export function StatePanel({
  eyebrow,
  title,
  children,
  actions,
  footnote,
  role,
}: {
  eyebrow?: string;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  footnote?: ReactNode;
  role?: "alert" | "status";
}) {
  return (
    <div className="mx-auto w-full max-w-[44rem] px-4 py-12 sm:px-6 sm:py-20">
      <section aria-labelledby="state-title" className={`${card} px-6 py-9 sm:px-12 sm:py-12`} role={role}>
        {eyebrow ? (
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">{eyebrow}</p>
        ) : null}
        <h1 className={`${pageTitle} ${eyebrow ? "mt-3" : ""}`} id="state-title">
          {title}
        </h1>
        <div className={`mt-4 flex flex-col gap-3 ${lede}`}>{children}</div>
        {actions ? <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">{actions}</div> : null}
        {footnote ? <div className="mt-8 border-t border-hero-border pt-6 text-sm leading-relaxed text-hero-muted">{footnote}</div> : null}
      </section>
    </div>
  );
}
