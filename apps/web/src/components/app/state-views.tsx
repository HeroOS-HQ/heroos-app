import Link from "next/link";

import { StatePanel } from "@/components/ui/state-panel";
import { buttonPrimary, buttonQuiet, buttonSecondary } from "@/components/ui/styles";
import { NOT_CONFIGURED_MESSAGE } from "@/lib/messages";

import { AppShell, SignOutButton } from "./app-shell";

/**
 * Full-page states shared by the signed-in routes. Fixed copy only; sign-in
 * and sign-up are plain links (the auth routes must never be prefetched), and
 * page links never prefetch authenticated content.
 */

export function NotConfiguredView() {
  return (
    <AppShell homeHref="/" signedIn={false}>
      <StatePanel role="status" title="Sign-in isn't set up here">
        <p>{NOT_CONFIGURED_MESSAGE}</p>
      </StatePanel>
    </AppShell>
  );
}

/** SIGNED_OUT (no session, or it ended). */
export function SignedOutView({ purpose = "workspace" }: { purpose?: "workspace" | "onboarding" }) {
  return (
    <AppShell homeHref="/" signedIn={false}>
      <StatePanel
        actions={
          purpose === "onboarding" ? (
            <>
              <a className={buttonPrimary} href="/auth/signup">
                Create an account
              </a>
              <a className={buttonSecondary} href="/auth/login">
                Sign in
              </a>
            </>
          ) : (
            <>
              <a className={buttonPrimary} href="/auth/login">
                Sign in
              </a>
              <Link className={buttonQuiet} href="/" prefetch={false}>
                Back to the HeroOS homepage
              </Link>
            </>
          )
        }
        title={purpose === "onboarding" ? "Create your account to get started" : "Please sign in"}
      >
        <p>
          {purpose === "onboarding"
            ? "Setting up your company takes a few minutes. First, create your HeroOS account or sign in."
            : "You're not signed in, or your session has ended. Sign in to open your workspace."}
        </p>
      </StatePanel>
    </AppShell>
  );
}

/** SESSION_EXPIRED: the API no longer accepts this session's token. */
export function SessionExpiredView() {
  return (
    <AppShell homeHref="/">
      <StatePanel
        actions={
          <a className={buttonPrimary} href="/auth/login">
            Sign in again
          </a>
        }
        role="alert"
        title="Your session has ended"
      >
        <p>For your security, please sign in again to continue.</p>
      </StatePanel>
    </AppShell>
  );
}

/** ACCESS_DENIED: the same answer for another Company, a revoked Membership or an unknown id. */
export function AccessDeniedView() {
  return (
    <AppShell>
      <StatePanel
        actions={
          <Link className={buttonPrimary} href="/workspaces" prefetch={false}>
            Go to my workspaces
          </Link>
        }
        role="alert"
        title="You don't have access to this workspace"
      >
        <p>
          This workspace doesn&apos;t exist or your account can&apos;t open it. If you expected access, ask your company
          administrator.
        </p>
      </StatePanel>
    </AppShell>
  );
}

/** API_UNAVAILABLE */
export function ApiUnavailableView({ retryHref }: { retryHref: string }) {
  return (
    <AppShell>
      <StatePanel
        actions={
          <>
            <a className={buttonPrimary} href={retryHref}>
              Try again
            </a>
            <SignOutButton />
          </>
        }
        role="alert"
        title="We can't reach HeroOS right now"
      >
        <p>The HeroOS service is temporarily unavailable. Please try again in a moment.</p>
      </StatePanel>
    </AppShell>
  );
}

/**
 * AUTHENTICATED_UNPROVISIONED, which the API cannot tell apart from a blocked
 * identity: a neutral welcome. Only a deliberate click starts onboarding, and
 * the registration API decides eligibility.
 */
export function UnprovisionedView() {
  return (
    <AppShell>
      <StatePanel
        actions={
          <Link className={buttonPrimary} href="/onboarding" prefetch={false}>
            Set up my company
          </Link>
        }
        eyebrow="Welcome to HeroOS"
        footnote={
          <p>
            Expected to see an existing workspace? Your access may have changed. Ask your company administrator or
            contact HeroOS support.
          </p>
        }
        title="Let's set up your company workspace"
      >
        <p>Tell us about your company and where it&apos;s licensed. It only takes a few minutes, and no HR experience is needed.</p>
      </StatePanel>
    </AppShell>
  );
}

/** NO_ACTIVE_WORKSPACE: a known account without any active Company access. */
export function NoActiveWorkspaceView() {
  return (
    <AppShell>
      <StatePanel
        actions={
          <>
            <Link className={buttonSecondary} href="/onboarding" prefetch={false}>
              Set up a new company
            </Link>
            <SignOutButton />
          </>
        }
        title="No active workspace"
      >
        <p>
          Your account doesn&apos;t currently have access to a company workspace. If you were expecting access, ask your
          company administrator.
        </p>
      </StatePanel>
    </AppShell>
  );
}
