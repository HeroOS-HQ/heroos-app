import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";
import { casesHref, SliceNotice } from "@/components/cases/cases-dashboard";
import { commonStateView, CompanyShell } from "@/components/cases/case-states";
import { NewCaseForm } from "@/components/cases/new-case-form";
import { ArrowLeftIcon } from "@/components/site/icons";
import { buttonQuiet, lede, pageTitle } from "@/components/ui/styles";
import { loadCases } from "@/lib/server/app-state";
import { WORKFLOW_DISCIPLINARY } from "@/lib/workflows/model";

export const metadata: Metadata = { title: "New Disciplinary case · HeroOS" };

/** New case for an administrator (ADMIN_ONLY otherwise); the API enforces it on create. */
export default function NewCasePage({ params }: PageProps<"/workspaces/[companyId]/cases/new">) {
  return (
    <Suspense fallback={<LoadingView />}>
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
    <CompanyShell details={state.details} workspaces={state.workspaces}>
      <div className="mx-auto flex w-full max-w-[44rem] flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
        <div>
          <a className={buttonQuiet} href={casesHref(company.id)}>
            <ArrowLeftIcon className="size-4" />
            Disciplinary cases
          </a>
          <h1 className={`${pageTitle} mt-3`}>New Disciplinary case</h1>
          <p className={`mt-2 ${lede}`}>
            Give the case a title. You&apos;ll then answer a few questions about what happened, at your own pace.
          </p>
        </div>
        <SliceNotice />
        <NewCaseForm companyId={company.id} />
      </div>
    </CompanyShell>
  );
}
