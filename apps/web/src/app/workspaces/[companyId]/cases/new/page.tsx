import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyShell } from "@/components/app/company-shell";
import { LoadingView } from "@/components/app/loading-view";
import { casesHref, disciplinaryCrumbs, SliceNotice } from "@/components/cases/cases-dashboard";
import { commonStateView } from "@/components/cases/case-states";
import { NewCaseForm } from "@/components/cases/new-case-form";
import { lede, pageTitle } from "@/components/ui/styles";
import { Breadcrumbs, pageGutter } from "@/components/workspace/page-banner";
import { loadCases } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "New Disciplinary case · HeroOS" };

/** New case for an administrator (ADMIN_ONLY otherwise); the API enforces it on create. */
export default function NewCasePage({ params }: PageProps<"/workspaces/[companyId]/cases/new">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <NewCaseContent params={params} />
    </Suspense>
  );
}

async function NewCaseContent({ params }: Pick<PageProps<"/workspaces/[companyId]/cases/new">, "params">) {
  const { companyId } = await params;
  const state = await loadCases(companyId, WORKFLOW_DISCIPLINARY);
  const common = commonStateView(state, `/workspaces/${encodeURIComponent(companyId)}/cases/new`);
  if (common !== null || state.kind !== "cases_ready") return common;
  const { company } = state.details;
  return (
    <CompanyShell current="cases" details={state.details} workspaces={state.workspaces}>
      <div className={`${pageGutter} pb-10 pt-3 sm:pt-4`}>
        <Breadcrumbs
          items={[...disciplinaryCrumbs(company.id), { label: "Cases", href: casesHref(company.id) }, { label: "New case" }]}
        />
        {/* A readable form width inside the full-width page; the notice sits beside it on wide screens. */}
        <div className="mt-2 grid gap-6 xl:grid-cols-[minmax(0,46rem)_minmax(18rem,24rem)] xl:items-start xl:gap-8">
          <div className="flex min-w-0 flex-col gap-6">
            <div>
              <h1 className={pageTitle}>New Disciplinary case</h1>
              <p className={`mt-2 ${lede}`}>
                Give the case a title. You&apos;ll then answer a few questions about what happened, at your own pace.
              </p>
            </div>
            <NewCaseForm companyId={company.id} />
          </div>
          <SliceNotice className="xl:mt-[4.5rem]" />
        </div>
      </div>
    </CompanyShell>
  );
}
