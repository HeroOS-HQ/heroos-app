import type { Metadata } from "next";
import { Suspense } from "react";

import { workspaceHeaderData } from "@/components/app/company-shell";
import { LoadingView } from "@/components/app/loading-view";
import { CaseNotFoundView, commonStateView } from "@/components/cases/case-states";
import { CaseWorkspace } from "@/components/cases/case-workspace";
import { loadCase } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "Case · HeroOS" };

/**
 * CASE_READY: one case in the Ask HeroOS workspace. The Case and Company ids
 * are only resource identifiers; the API authorizes every request (Membership
 * and RLS).
 */
export default function CasePage({ params }: PageProps<"/workspaces/[companyId]/cases/[caseId]">) {
  return (
    <Suspense fallback={<LoadingView label="Loading the case…" layout="full" />}>
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
  if (state.kind === "case_not_found") {
    return <CaseNotFoundView cases={state.cases} details={state.details} workspaces={state.workspaces} />;
  }
  if (state.kind !== "case_ready") return null;
  return (
    // Keyed by Case: opening another Case never carries form state over.
    <CaseWorkspace
      header={workspaceHeaderData(state.details, state.workspaces, state.cases)}
      initialView={state.view}
      key={state.view.case.id}
    />
  );
}
