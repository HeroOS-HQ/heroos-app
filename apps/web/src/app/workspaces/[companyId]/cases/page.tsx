import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";
import { CasesDashboard } from "@/components/cases/cases-dashboard";
import { commonStateView, CompanyShell } from "@/components/cases/case-states";
import { loadCases } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "Disciplinary cases · HeroOS" };

/** CASES_READY: the Company's Disciplinary Cases; the API authorizes every request. */
export default function CasesPage({ params }: PageProps<"/workspaces/[companyId]/cases">) {
  return (
    <Suspense fallback={<LoadingView label="Loading cases…" />}>
      <CasesContent params={params} />
    </Suspense>
  );
}

async function CasesContent({ params }: Pick<PageProps<"/workspaces/[companyId]/cases">, "params">) {
  const { companyId } = await params;
  const state = await loadCases(companyId, WORKFLOW_DISCIPLINARY);
  const common = commonStateView(state, `/workspaces/${encodeURIComponent(companyId)}/cases`);
  if (common !== null || state.kind !== "cases_ready") return common;
  const { company, membership } = state.details;
  return (
    <CompanyShell details={state.details} workspaces={state.workspaces}>
      <CasesDashboard
        canCreate={membership?.role === "company_admin"}
        cases={state.cases}
        companyId={company.id}
        companyName={company.name}
      />
    </CompanyShell>
  );
}
