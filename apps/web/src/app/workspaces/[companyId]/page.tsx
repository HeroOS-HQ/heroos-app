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
import { type AskMode, AskWorkspace } from "@/components/ask/ask-workspace";
import { ASK_WORKFLOW } from "@/lib/ask/model";
import { loadCases } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Ask HeroOS · HeroOS" };

/**
 * Ask HeroOS, the signed-in home of one Company (approved Oct 20 design,
 * Page 1). The URL id is only a resource identifier: the API authorizes every
 * request. `?cases=open` opens the Cases drawer (the old case-list URLs lead here).
 */
export default function AskPage({ params, searchParams }: PageProps<"/workspaces/[companyId]">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <AskContent params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function AskContent({ params, searchParams }: Pick<PageProps<"/workspaces/[companyId]">, "params" | "searchParams">) {
  const [{ companyId }, query] = await Promise.all([params, searchParams]);
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
      return <ApiUnavailableView retryHref={`/workspaces/${encodeURIComponent(companyId)}`} />;
    default:
      break;
  }
  // Administrators open cases; members can't (yet), and an API without workflows can't either.
  const mode: AskMode = state.kind === "cases_ready" ? "ready" : state.kind === "admin_only" ? "members" : "unavailable";
  const cases = state.kind === "cases_ready" ? state.cases : null;
  return (
    <CompanyShell
      cases={cases}
      details={state.details}
      initialCasesOpen={query.cases === "open"}
      quiet={false}
      workspaces={state.workspaces}
    >
      <AskWorkspace companyId={state.details.company.id} mode={mode} returning={(cases?.length ?? 0) > 0} />
    </CompanyShell>
  );
}
