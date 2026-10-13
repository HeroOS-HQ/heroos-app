import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { LoadingView } from "@/components/app/loading-view";
import {
  ApiUnavailableView,
  NoActiveWorkspaceView,
  NotConfiguredView,
  SessionExpiredView,
  SignedOutView,
  UnprovisionedView,
} from "@/components/app/state-views";
import { WorkspaceChooser } from "@/components/workspace/workspace-chooser";
import { loadDiscovery } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Your workspaces · HeroOS" };

/** Workspace discovery: `GET /me/companies` decides what this user can open. */
export default function WorkspacesPage() {
  return (
    <Suspense fallback={<LoadingView />}>
      <WorkspacesContent />
    </Suspense>
  );
}

async function WorkspacesContent() {
  const state = await loadDiscovery();
  switch (state.kind) {
    case "not_configured":
      return <NotConfiguredView />;
    case "signed_out":
      return <SignedOutView />;
    case "session_expired":
      return <SessionExpiredView />;
    case "unprovisioned_or_blocked":
      return <UnprovisionedView />;
    case "no_active_workspace":
      return <NoActiveWorkspaceView />;
    case "single":
      redirect(`/workspaces/${encodeURIComponent(state.workspace.companyId)}`);
    case "workspace_selection":
      return (
        <AppShell>
          <WorkspaceChooser workspaces={state.workspaces} />
        </AppShell>
      );
    case "api_unavailable":
      return <ApiUnavailableView retryHref="/workspaces" />;
  }
}
