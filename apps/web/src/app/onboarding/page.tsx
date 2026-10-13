import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { LoadingView } from "@/components/app/loading-view";
import { NotConfiguredView, SessionExpiredView, SignedOutView } from "@/components/app/state-views";
import { OnboardingWizard } from "@/components/onboarding/onboarding-wizard";
import { discoveryState, sessionGate } from "@/lib/server/app-state";
import { discoverWorkspaces } from "@/lib/server/heroos-api";

export const metadata: Metadata = { title: "Set up your company · HeroOS" };

/**
 * Founder onboarding (Screens B–D). Requires a signed-in session; nothing is
 * created until the founder confirms on the review step. Workspace discovery
 * only adds a hint when the account already has a workspace: it never decides
 * whether this person may register (the registration API does).
 */
export default function OnboardingPage() {
  return (
    <Suspense fallback={<LoadingView label="Loading…" />}>
      <OnboardingContent />
    </Suspense>
  );
}

async function OnboardingContent() {
  const gate = await sessionGate();
  if (gate.kind === "not_configured") return <NotConfiguredView />;
  if (gate.kind === "signed_out") return <SignedOutView purpose="onboarding" />;
  const discovery = discoveryState(await discoverWorkspaces(gate.accessToken, gate.config));
  if (discovery.kind === "session_expired") return <SessionExpiredView />;
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
