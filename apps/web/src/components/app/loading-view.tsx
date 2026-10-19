import { AppShell } from "./app-shell";

/** Shown while a signed-in page reads the session and the API. */
export function LoadingView({
  label = "Loading your workspace…",
  layout,
}: {
  label?: string;
  /** full: a Company's page is loading (its frame spans the window). */
  layout?: "contained" | "full";
}) {
  return (
    <AppShell layout={layout} signedIn={false}>
      <div className="mx-auto flex w-full max-w-[44rem] flex-col items-center gap-4 px-4 py-24" role="status">
        <svg aria-hidden="true" className="size-8 animate-spin text-hero-blue motion-reduce:animate-none" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-20" cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeLinecap="round" strokeWidth="3" />
        </svg>
        <p className="text-base font-semibold text-hero-muted">{label}</p>
      </div>
    </AppShell>
  );
}
