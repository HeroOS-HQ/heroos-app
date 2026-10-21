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
import { BlueprintPage } from "@/components/blueprint/blueprint-page";
import { StatePanel } from "@/components/ui/state-panel";
import { ASK_WORKFLOW } from "@/lib/ask/model";
import { loadCases } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Company Blueprint · HeroOS" };

/**
 * Page 2, the Company Blueprint (approved Oct 20 design), editable by an
 * administrator per the API's membership answer and read-only otherwise. The
 * API enforces the role on save. (The URL keeps its earlier name, `settings`,
 * so saved links still work.)
 */
export default function BlueprintRoute({ params }: PageProps<"/workspaces/[companyId]/settings">) {
  return (
    <Suspense fallback={<LoadingView label="Loading the Company Blueprint…" layout="full" />}>
      <BlueprintContent params={params} />
    </Suspense>
  );
}

async function BlueprintContent({ params }: Pick<PageProps<"/workspaces/[companyId]/settings">, "params">) {
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
      return <ApiUnavailableView retryHref={`/workspaces/${encodeURIComponent(companyId)}/settings`} />;
    default:
      break;
  }
  const { company, membership, blueprint } = state.details;
  return (
    <CompanyShell
      cases={state.kind === "cases_ready" ? state.cases : null}
      current="blueprint"
      details={state.details}
      workspaces={state.workspaces}
    >
      {blueprint === null ? (
        <StatePanel role="status" title="The Company Blueprint isn't available yet">
          <p>This HeroOS service doesn&apos;t provide company profiles yet.</p>
        </StatePanel>
      ) : (
        // Keyed by Company: switching Companies never carries form state over.
        <BlueprintPage
          companyId={company.id}
          companyName={company.name}
          editable={membership?.canUpdateBlueprint === true}
          initial={blueprint}
          key={company.id}
        />
      )}
    </CompanyShell>
  );
}
