import type { ReactNode } from "react";

import { WorkspaceBrandMark } from "@/components/site/brand-mark";
import { DemoNotice } from "@/components/site/demo-notice";

import { BackForwardCacheGuard } from "./back-forward-cache-guard";

/** POST-only sign-out (the route refuses cross-site requests). */
export function SignOutButton({ className }: { className?: string }) {
  return (
    <form action="/auth/logout" className={className} method="post">
      <button
        className="inline-flex min-h-11 items-center rounded-full px-3 text-sm font-bold text-hero-blue-ink transition-colors duration-150 hover:bg-hero-blue-tint"
        type="submit"
      >
        Sign out
      </button>
    </form>
  );
}

type ShellProps = {
  children: ReactNode;
  /** Short context shown beside the logo, e.g. "Company setup" or the Company name. */
  context?: string;
  /** Show sign-out (signed-in pages). */
  signedIn?: boolean;
  /** Where the logo leads. */
  homeHref?: string;
  /** full: header and footer span the window, like a Company's pages (e.g. while one loads). */
  layout?: "contained" | "full";
};

/**
 * The frame of the signed-in pages outside one Company's workspace (choosing a
 * workspace, onboarding, sign-in states): skip link, header (logo, context,
 * sign-out), main content and a quiet footer with the environment notice. A
 * Company's own pages use `CompanyFrame` (full width, with its navigation).
 */
export function AppShell({ children, context, signedIn = true, homeHref = "/workspaces", layout = "contained" }: ShellProps) {
  const width = layout === "full" ? "w-full lg:px-6" : "mx-auto w-full max-w-[1240px]";
  return (
    <>
      {signedIn ? <BackForwardCacheGuard /> : null}
      <a
        className="sr-only z-[60] rounded-full bg-hero-yellow px-5 py-3 font-bold text-hero-navy focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
        href="#main"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-hero-border bg-white/95 backdrop-blur-md">
        <div className={`${width} flex min-h-16 items-center justify-between gap-3 px-4 py-2 sm:min-h-[72px] sm:px-8`}>
          <div className="flex min-w-0 items-center gap-3 sm:gap-4">
            <a
              aria-label="HeroOS home"
              className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg"
              href={homeHref}
            >
              <WorkspaceBrandMark />
            </a>
            {context ? (
              <>
                <span aria-hidden="true" className="hidden h-7 w-px bg-hero-border sm:block" />
                <p className="hidden min-w-0 truncate text-sm font-semibold text-hero-muted sm:block">{context}</p>
              </>
            ) : null}
          </div>
          {signedIn ? (
            <div className="flex shrink-0 items-center gap-1 sm:gap-2">
              <SignOutButton />
            </div>
          ) : null}
        </div>
      </header>
      {/* scroll-mt: client navigation and the skip link scroll here; keep it clear of the sticky header. */}
      <main className="flex-1 scroll-mt-20" id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="border-t border-hero-border bg-white">
        <div className={`${width} flex flex-col gap-1 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-8`}>
          <DemoNotice />
          <p className="text-sm text-hero-muted">© HeroOS</p>
        </div>
      </footer>
    </>
  );
}
