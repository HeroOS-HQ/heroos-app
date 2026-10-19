import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { LoadingView } from "@/components/app/loading-view";
import { NotConfiguredView, SessionExpiredView, SignedOutView } from "@/components/app/state-views";
import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard";
import { afterSignupRedirect, discoveryState, sessionGate } from "@/lib/server/app-state";
import { discoverWorkspaces } from "@/lib/server/heroos-api";

export const metadata: Metadata = { title: "Set up your company · HeroOS" };

/**
 * Founder onboarding (Screens B–D). Requires a signed-in session; nothing is
 * created until the founder confirms on the review step. Workspace discovery
 * only adds a hint when the account already has a workspace: it never decides
 * whether this person may register (the registration API does). Straight after
 * hosted sign-up (`start=signup`, the fixed sign-up landing) an account with a
 * workspace goes to it instead.
 */
export default function OnboardingPage({ searchParams }: PageProps<"/onboarding">) {
  return (
    <Suspense fallback={<LoadingView label="Loading…" />}>
      <OnboardingContent searchParams={searchParams} />
    </Suspense>
  );
}

async function OnboardingContent({ searchParams }: Pick<PageProps<"/onboarding">, "searchParams">) {
  const [gate, params] = await Promise.all([sessionGate(), searchParams]);
  if (gate.kind === "not_configured") return <NotConfiguredView />;
  if (gate.kind === "signed_out") return <SignedOutView purpose="onboarding" />;
  const discovery = discoveryState(await discoverWorkspaces(gate.accessToken, gate.config));
  if (discovery.kind === "session_expired") return <SessionExpiredView />;
  const landing = params.start === "signup" ? afterSignupRedirect(discovery) : null;
  if (landing !== null) redirect(landing);
  const existing =
    discovery.kind === "single"
      ? [discovery.workspace]
      : discovery.kind === "workspace_selection"
        ? discovery.workspaces
        : [];
  return (
    <AppShell context="Company setup">
      <OnboardingWizard existingWorkspaces={existing.map(({ companyId, name }) => ({ companyId, name }))} />
    </AppShell>
  );
}
