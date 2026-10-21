import type { ReactNode } from "react";

import { LogoSymbol } from "@/components/site/brand-mark";
import { DemoNotice } from "@/components/site/demo-notice";
import { UserIcon } from "@/components/site/icons";

import { BackForwardCacheGuard } from "./back-forward-cache-guard";

/**
 * The signed-in workspace's look, shared by Ask HeroOS, the Company Blueprint
 * and Company Space (JJ's approved Oct 20 design package,
 * `src/app/design-review/oct20`): a quiet background, one header, no
 * permanent navigation. Presentational only; usable from server and client
 * components alike.
 */

/** A round, quiet header control (icon or icon + label). */
export const iconButton =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full px-2.5 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-navy/[0.06]";

/** A header control that shows when its panel is open (`aria-expanded`). */
export const ghostButton =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full px-3 text-[0.9375rem] font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-expanded:bg-white aria-expanded:shadow-[0_0_0_1px_rgb(14_30_61/0.1)]";

export const quietLink =
  "inline-flex min-h-9 items-center gap-1.5 rounded-lg text-[0.875rem] font-bold text-hero-blue-ink underline-offset-4 hover:underline max-sm:min-h-11";

export const outlineButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-hero-navy/15 bg-white px-4 text-[0.9375rem] font-bold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.05)] transition-colors duration-150 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60";

export const primaryButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-hero-navy px-5 text-[0.9375rem] font-bold text-white shadow-[0_10px_20px_-10px_rgb(14_30_61/0.9)] transition-colors duration-150 hover:bg-[#182c55] disabled:cursor-not-allowed disabled:opacity-70";

/** The one white sheet the Blueprint and Company Space are written on. */
export const sheet =
  "rounded-[1.75rem] border border-hero-navy/[0.08] bg-white px-5 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_30px_60px_-40px_rgb(14_30_61/0.35)] sm:px-10";

/**
 * Two soft lights in the logo's colours behind every page, dimmed (`quiet`)
 * wherever there is something to read. Radial gradients, not blur filters:
 * large blurs band into visible rings. Fixed, so the page scrolls over it.
 */
export function WorkspaceBackdrop({ quiet }: { quiet: boolean }) {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,#fbfaf8_0%,#f4f3ef_100%)]" />
      <div className={quiet ? "opacity-40" : ""}>
        <div className="absolute left-1/2 top-[40%] size-[30rem] -translate-x-[80%] -translate-y-1/2 bg-[radial-gradient(closest-side,rgb(61_107_196/0.13),rgb(61_107_196/0.05)_55%,transparent)] sm:size-[46rem]" />
        <div className="absolute left-1/2 top-[44%] size-[28rem] -translate-x-[20%] -translate-y-1/2 bg-[radial-gradient(closest-side,rgb(255_212_1/0.18),rgb(255_212_1/0.06)_55%,transparent)] sm:size-[44rem]" />
      </div>
    </div>
  );
}

/**
 * HeroOS's own mark where HeroOS speaks: in the conversation and above the
 * question. The invisible strut keeps the text baseline of the approved design.
 */
export function AdviserMark({ size = "turn", breathe = false }: { size?: "turn" | "hero"; breathe?: boolean }) {
  const hero = size === "hero";
  return (
    <span
      aria-hidden="true"
      className={`relative inline-flex shrink-0 items-center justify-center ${hero ? "size-14 sm:size-16" : "size-8"} ${
        breathe ? "ws-breathe rounded-full" : ""
      }`}
    >
      <span className={hero ? "h-7 w-0 sm:h-8" : "h-[0.95rem] w-0"} />
      <LogoSymbol className={`absolute ${hero ? "size-12 sm:size-14" : "size-7"}`} />
    </span>
  );
}

/**
 * The signed-in person. HeroOS doesn't hold their name in this app (the
 * session carries an access token only), so the avatar is a neutral person
 * symbol rather than invented initials.
 */
export function PersonAvatar({ className = "size-8" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center rounded-full bg-hero-navy text-white ${className}`}
    >
      <UserIcon className="size-[55%]" />
    </span>
  );
}

/**
 * The page around every signed-in screen: background, skip link, the header
 * the page brings, the main region and the environment notice. `overlay` (a
 * modal panel such as the case status) is rendered above everything, the
 * header included: inside the main region it would sit under the sticky header.
 */
export function WorkspaceLayout({
  header,
  quiet,
  overlay,
  children,
}: {
  header: ReactNode;
  quiet: boolean;
  overlay?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="relative isolate flex min-h-dvh flex-col">
      <WorkspaceBackdrop quiet={quiet} />
      <BackForwardCacheGuard />
      <a
        className="sr-only z-[60] rounded-full bg-hero-yellow px-5 py-3 font-bold text-hero-navy focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
        href="#main"
      >
        Skip to content
      </a>
      {header}
      <main className="relative z-10 flex min-w-0 flex-1 scroll-mt-20 flex-col" id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="relative z-10 px-4 pb-4 pt-6 text-center">
        <DemoNotice className="text-xs" />
      </footer>
      {overlay}
    </div>
  );
}
