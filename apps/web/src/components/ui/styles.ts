/**
 * Shared class names for the signed-in app (onboarding, workspace, settings),
 * built on the HeroOS tokens in globals.css. Plain constants, no component
 * library: the CSP forbids inline style attributes, so all styling is classes.
 */

const focusRing = "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue";

export const buttonPrimary =
  `inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-hero-yellow px-7 text-base font-bold text-hero-navy shadow-[0_8px_20px_-10px_rgb(255_212_1/0.9)] transition-[box-shadow,transform,background-color] duration-200 hover:-translate-y-px hover:bg-[#f6cb00] disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

export const buttonSecondary =
  `inline-flex min-h-12 items-center justify-center gap-2 rounded-full border border-hero-control bg-white px-6 text-base font-bold text-hero-navy transition-colors duration-200 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

export const buttonQuiet =
  `inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-base font-bold text-hero-blue-ink underline-offset-4 hover:underline ${focusRing}`;

export const card = "rounded-3xl border border-hero-border bg-white shadow-hero-card";

export const pageTitle = "text-[1.75rem] font-extrabold leading-tight tracking-[-0.025em] text-hero-navy sm:text-[2.125rem]";

export const sectionTitle = "text-lg font-extrabold tracking-[-0.01em] text-hero-navy";

export const lede = "text-base leading-relaxed text-hero-muted sm:text-lg";

export const label = "block text-[0.9375rem] font-bold text-hero-navy";

export const hint = "mt-1 block text-sm leading-relaxed text-hero-muted";

export const input =
  "mt-2 block min-h-12 w-full rounded-xl border border-hero-control bg-white px-4 py-3 text-base text-hero-navy transition-colors duration-150 placeholder:text-hero-muted focus:border-hero-blue aria-[invalid=true]:border-hero-danger aria-[invalid=true]:border-2";

export const fieldError = "mt-2 flex items-start gap-1.5 text-sm font-semibold text-hero-danger";
