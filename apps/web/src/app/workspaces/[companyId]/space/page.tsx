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
import { SpacePage } from "@/components/space/space-page";
import { ASK_WORKFLOW } from "@/lib/ask/model";
import { loadCases } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Company Space · HeroOS" };

/**
 * Page 3, Company Space (approved Oct 20 design): this account's access and the
 * company's overview. The URL id is only a resource identifier; the API
 * authorizes every request.
 */
export default function SpaceRoute({ params }: PageProps<"/workspaces/[companyId]/space">) {
  return (
    <Suspense fallback={<LoadingView label="Loading Company Space…" layout="full" />}>
      <SpaceContent params={params} />
    </Suspense>
  );
}

async function SpaceContent({ params }: Pick<PageProps<"/workspaces/[companyId]/space">, "params">) {
  const { companyId } = await params;
  const state = await loadCases(companyId, ASK_WORKFLOW);
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
      return <ApiUnavailableView retryHref={`/workspaces/${encodeURIComponent(companyId)}/space`} />;
    default:
      return (
        <CompanyShell
          cases={state.kind === "cases_ready" ? state.cases : null}
          current="space"
          details={state.details}
          workspaces={state.workspaces}
        >
          <SpacePage details={state.details} />
        </CompanyShell>
      );
  }
}
