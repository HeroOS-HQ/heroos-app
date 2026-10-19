import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyShell } from "@/components/app/company-shell";
import { LoadingView } from "@/components/app/loading-view";
import {
  AccessDeniedView,
  ApiUnavailableView,
  NotConfiguredView,
  SessionExpiredView,
  SignedOutView,
} from "@/components/app/state-views";
import { WorkspaceHome } from "@/components/workspace/workspace-home";
import { loadWorkspace } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Dashboard · HeroOS" };

/** WORKSPACE_READY for one Company (its dashboard); the URL id is authorized by the API on every request. */
export default function WorkspacePage({ params }: PageProps<"/workspaces/[companyId]">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <WorkspaceContent params={params} />
    </Suspense>
  );
}

async function WorkspaceContent({ params }: Pick<PageProps<"/workspaces/[companyId]">, "params">) {
  const { companyId } = await params;
  const state = await loadWorkspace(companyId);
  switch (state.kind) {
    case "not_configured":
      return <NotConfiguredView />;
    case "signed_out":
      return <SignedOutView />;
    case "session_expired":
      return <SessionExpiredView />;
    case "access_denied":
      return <AccessDeniedView />;
    case "api_unavailable":
      return <ApiUnavailableView retryHref={`/workspaces/${encodeURIComponent(companyId)}`} />;
    case "workspace_ready":
      return (
        <CompanyShell current="dashboard" details={state.details} workspaces={state.workspaces}>
          <WorkspaceHome details={state.details} />
        </CompanyShell>
      );
  }
}
