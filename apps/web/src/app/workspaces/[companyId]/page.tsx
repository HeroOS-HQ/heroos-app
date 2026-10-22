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
import { chatOnlyDemoRequired, loadAskGateway, loadCases } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Ask HeroOS · HeroOS" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Ask HeroOS, the signed-in home of one Company (approved Oct 20 design,
 * Page 1). The URL id is only a resource identifier: the API authorizes every
 * request. `?cases=open` opens the Cases drawer (the old case-list URLs lead here).
 * When the API says its AI gateway can answer here (M2-NEW-05), Ask is a
 * conversation with HeroOS; otherwise it opens a case, as before.
 * `?conversation={id}` reopens a stored conversation (M2-NEW-07); the API
 * decides whether this administrator may read it.
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
  const [state, gateway] = await Promise.all([loadCases(companyId, ASK_WORKFLOW), loadAskGateway(companyId)]);
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
  const conversationId = typeof query.conversation === "string" && UUID.test(query.conversation) ? query.conversation : null;
  return (
    <CompanyShell
      cases={cases}
      details={state.details}
      initialCasesOpen={query.cases === "open"}
      quiet={false}
      workspaces={state.workspaces}
    >
      <AskWorkspace
        chatOnlyDemo={chatOnlyDemoRequired()}
        companyId={state.details.company.id}
        conversation={mode === "ready" ? gateway : null}
        conversationId={mode === "ready" ? conversationId : null}
        mode={mode}
        returning={(cases?.length ?? 0) > 0}
      />
    </CompanyShell>
  );
}
