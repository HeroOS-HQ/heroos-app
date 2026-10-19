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
import { CompanySettingsForm } from "@/components/settings/company-settings-form";
import { Notice } from "@/components/ui/notice";
import { card, lede, pageTitle, sectionTitle } from "@/components/ui/styles";
import { CompanyFacts } from "@/components/workspace/company-facts";
import { JurisdictionStatus } from "@/components/workspace/jurisdiction-status";
import { pageGutter } from "@/components/workspace/page-banner";
import { loadWorkspace } from "@/lib/server/app-state";

export const metadata: Metadata = { title: "Company details · HeroOS" };

/**
 * Screen H. PROFILE_EDITABLE for an administrator (per the API's membership
 * answer), PROFILE_READ_ONLY for a member. The API enforces the role on save.
 */
export default function SettingsPage({ params }: PageProps<"/workspaces/[companyId]/settings">) {
  return (
    <Suspense fallback={<LoadingView label="Loading company details…" layout="full" />}>
      <SettingsContent params={params} />
    </Suspense>
  );
}

async function SettingsContent({ params }: Pick<PageProps<"/workspaces/[companyId]/settings">, "params">) {
  const { companyId } = await params;
  const state = await loadWorkspace(companyId);
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
    case "workspace_ready":
      break;
  }
  const { company, membership, blueprint } = state.details;
  const editable = membership?.canUpdateBlueprint === true && blueprint !== null;
  return (
    <CompanyShell current="blueprint" details={state.details} workspaces={state.workspaces}>
      {/* A readable form width inside the full-width page. */}
      <div className={`${pageGutter} flex max-w-[56rem] flex-col gap-6 pb-10 pt-7 sm:pt-10`}>
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-hero-blue-ink">Company Blueprint</p>
          <h1 className={`${pageTitle} mt-2`}>Company details</h1>
          <p className={`mt-2 ${lede}`}>
            {editable
              ? "Keep your company profile up to date. Changes are saved only when you select “Save changes”."
              : "Your company's saved profile."}
          </p>
        </div>
        {blueprint === null ? (
          <Notice title="Company profile isn't available yet">
            This HeroOS service doesn&apos;t provide company profiles yet.
          </Notice>
        ) : editable ? (
          // Keyed by Company: switching Companies never carries form state over.
          <CompanySettingsForm companyId={company.id} companyName={company.name} initial={blueprint} key={company.id} />
        ) : (
          <>
            <Notice title="View only">Only company administrators can change these details.</Notice>
            <section aria-labelledby="profile-heading" className={`${card} p-5 sm:p-8`}>
              <h2 className={sectionTitle} id="profile-heading">
                Company profile
              </h2>
              <div className="mt-3">
                <CompanyFacts blueprint={blueprint} />
              </div>
              <div className="mt-5">
                <JurisdictionStatus jurisdiction={blueprint.jurisdiction} />
              </div>
            </section>
          </>
        )}
      </div>
    </CompanyShell>
  );
}
