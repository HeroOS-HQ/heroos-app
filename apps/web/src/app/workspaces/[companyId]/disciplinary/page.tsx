import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyShell } from "@/components/app/company-shell";
import { LoadingView } from "@/components/app/loading-view";
import { commonStateView } from "@/components/cases/case-states";
import { DisciplineOverview } from "@/components/workspace/discipline-overview";
import { loadCases } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "Conduct & Discipline · HeroOS" };

/**
 * The Disciplinary workflow's overview for a Company administrator, with the
 * Company's recent Cases (ADMIN_ONLY otherwise); the API authorizes every request.
 */
export default function DisciplinaryPage({ params }: PageProps<"/workspaces/[companyId]/disciplinary">) {
  return (
    <Suspense fallback={<LoadingView label="Loading Conduct & Discipline…" layout="full" />}>
      <DisciplinaryContent params={params} />
    </Suspense>
  );
}

async function DisciplinaryContent({ params }: Pick<PageProps<"/workspaces/[companyId]/disciplinary">, "params">) {
  const { companyId } = await params;
  const state = await loadCases(companyId, WORKFLOW_DISCIPLINARY);
  const common = commonStateView(state, `/workspaces/${encodeURIComponent(companyId)}/disciplinary`, "services");
  if (common !== null || state.kind !== "cases_ready") return common;
  return (
    <CompanyShell current="services" details={state.details} workspaces={state.workspaces}>
      <DisciplineOverview cases={state.cases} details={state.details} />
    </CompanyShell>
  );
}
