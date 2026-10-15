import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";
import { CaseNotFoundView, commonStateView, CompanyShell } from "@/components/cases/case-states";
import { CaseWorkspace } from "@/components/cases/case-workspace";
import { loadCase } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "Disciplinary case · HeroOS" };

/**
 * CASE_READY: the guided Case workspace. The Case and Company ids are only
 * resource identifiers; the API authorizes every request (Membership and RLS).
 */
export default function CasePage({ params }: PageProps<"/workspaces/[companyId]/cases/[caseId]">) {
  return (
    <Suspense fallback={<LoadingView label="Loading the case…" />}>
      <CaseContent params={params} />
    </Suspense>
  );
}

async function CaseContent({ params }: Pick<PageProps<"/workspaces/[companyId]/cases/[caseId]">, "params">) {
  const { companyId, caseId } = await params;
  const state = await loadCase(companyId, WORKFLOW_DISCIPLINARY, caseId);
  const retry = `/workspaces/${encodeURIComponent(companyId)}/cases/${encodeURIComponent(caseId)}`;
  const common = commonStateView(state, retry);
  if (common !== null) return common;
  if (state.kind === "case_not_found") return <CaseNotFoundView details={state.details} workspaces={state.workspaces} />;
  if (state.kind !== "case_ready") return null;
  return (
    <CompanyShell details={state.details} workspaces={state.workspaces}>
      {/* Keyed by Case: opening another Case never carries form state over. */}
      <CaseWorkspace cases={state.cases} companyId={state.details.company.id} initialView={state.view} key={state.view.case.id} />
    </CompanyShell>
  );
}
