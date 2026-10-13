import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell } from "@/components/app/app-shell";
import { LoadingView } from "@/components/app/loading-view";
import {
  AccessDeniedView,
  ApiUnavailableView,
  NotConfiguredView,
  SessionExpiredView,
  SignedOutView,
} from "@/components/app/state-views";
import { WorkspaceReady } from "@/components/workspace/workspace-ready";
import { loadWorkspace } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Workspace ready · HeroOS" };

/**
 * Screen E. Reached only after the BFF confirmed a registration. `outcome`
 * selects wording only; the Company, role and readiness are read from the API,
 * which authorizes the id like any other request.
 */
export default function WorkspaceReadyPage({ params, searchParams }: PageProps<"/workspaces/[companyId]/ready">) {
  return (
    <Suspense fallback={<LoadingView label="Opening your workspace…" />}>
      <ReadyContent params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function ReadyContent({
  params,
  searchParams,
}: Pick<PageProps<"/workspaces/[companyId]/ready">, "params" | "searchParams">) {
  const [{ companyId }, query] = await Promise.all([params, searchParams]);
  const outcome = query.outcome === "existing" ? "existing" : "created";
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
        <AppShell context={state.details.company.name}>
          <WorkspaceReady details={state.details} outcome={outcome} />
        </AppShell>
      );
  }
}
