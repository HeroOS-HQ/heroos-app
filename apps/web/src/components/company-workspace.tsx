import type { ApiFailure, CaseSummary, Company } from "@/lib/server/heroos-api";

/**
 * Presentational view of the demo workspace. Every state maps to a fixed message:
 * no API or identity-provider error text is ever rendered.
 */

export type WorkspaceView =
  | { kind: "not_configured" }
  | { kind: "signed_out"; authOutcome: string | null }
  | { kind: "error"; failure: ApiFailure }
  | { kind: "signed_in"; company: Company; cases: CaseSummary[] };

const AUTH_MESSAGES: Record<string, string> = {
  failed: "Sign-in could not be completed. Please try again.",
  cancelled: "Sign-in was cancelled.",
  expired: "The sign-in attempt expired. Please try again.",
};

const FAILURE_MESSAGES: Record<ApiFailure, string> = {
  unauthenticated: "Your session has expired. Please sign in again.",
  forbidden: "Your account does not have access to the demo company.",
  not_found: "The demo company could not be found.",
  unavailable: "The HeroOS service is temporarily unavailable. Please try again later.",
};

const buttonClass =
  "inline-flex h-10 items-center rounded-full bg-zinc-900 px-5 text-sm font-medium text-white hover:bg-zinc-700";

function SignInLink() {
  // A plain link, not next/link: the login route must not be prefetched.
  return (
    <a className={buttonClass} href="/auth/login">
      Sign in
    </a>
  );
}

function SignOutForm() {
  return (
    <form action="/auth/logout" method="post">
      <button className={buttonClass} type="submit">
        Sign out
      </button>
    </form>
  );
}

export function CompanyWorkspace({ view }: { view: WorkspaceView }) {
  switch (view.kind) {
    case "not_configured":
      return <p role="status">Sign-in is not configured for this deployment.</p>;
    case "signed_out":
      return (
        <section className="flex flex-col items-start gap-4">
          {view.authOutcome && AUTH_MESSAGES[view.authOutcome] ? (
            <p role="alert">{AUTH_MESSAGES[view.authOutcome]}</p>
          ) : null}
          <SignInLink />
        </section>
      );
    case "error":
      return (
        <section className="flex flex-col items-start gap-4">
          <p role="alert">{FAILURE_MESSAGES[view.failure]}</p>
          {view.failure === "unauthenticated" ? <SignInLink /> : <SignOutForm />}
        </section>
      );
    case "signed_in":
      return (
        <section className="flex flex-col gap-6">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold">{view.company.name}</h2>
            <SignOutForm />
          </div>
          {view.cases.length === 0 ? (
            <p>No cases.</p>
          ) : (
            <ul className="flex flex-col gap-2" aria-label="Cases">
              {view.cases.map((item) => (
                <li key={item.id} className="rounded-lg border border-zinc-200 px-4 py-3">
                  <p className="font-medium">{item.title}</p>
                  <p className="text-sm text-zinc-600">{item.caseType}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      );
  }
}
