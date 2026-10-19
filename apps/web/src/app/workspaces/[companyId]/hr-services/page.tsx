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
import { HrServices } from "@/components/workspace/hr-services";
import { loadWorkspace } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "HR Services · HeroOS" };

/** The Company's HR workflows and what each offers this account; the API authorizes the Company id. */
export default function HrServicesPage({ params }: PageProps<"/workspaces/[companyId]/hr-services">) {
  return (
    <Suspense fallback={<LoadingView label="Loading HR services…" layout="full" />}>
      <HrServicesContent params={params} />
    </Suspense>
  );
}

async function HrServicesContent({ params }: Pick<PageProps<"/workspaces/[companyId]/hr-services">, "params">) {
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
      return <ApiUnavailableView retryHref={`/workspaces/${encodeURIComponent(companyId)}/hr-services`} />;
    case "workspace_ready":
      return (
        <CompanyShell current="services" details={state.details} workspaces={state.workspaces}>
          <HrServices details={state.details} />
        </CompanyShell>
      );
  }
}
