import { Suspense } from "react";

import { AppName } from "@/components/app-name";
import {
  authOutcomeMessage,
  CompanyWorkspace,
  NOT_CONFIGURED_MESSAGE,
  type WorkspaceView,
} from "@/components/company-workspace";
import { DemoNotice } from "@/components/site/demo-notice";
import { LandingPage } from "@/components/site/landing-page";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { readAuthConfig } from "@/lib/server/config";
import { getCompanyOverview } from "@/lib/server/heroos-api";
import { readSession } from "@/lib/server/session";

const AUTH_OUTCOMES = new Set(["failed", "cancelled", "expired", "unavailable"]);

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<SiteHeader variant="workspace" />}>
      <HomeContent searchParams={searchParams} />
    </Suspense>
  );
}

async function HomeContent({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const params = await searchParams;
  const rawOutcome = typeof params.auth === "string" ? params.auth : null;
  const authOutcome = rawOutcome !== null && AUTH_OUTCOMES.has(rawOutcome) ? rawOutcome : null;
  // Only a hint: it is used solely to pick among Companies the API has authorized.
  const requestedCompany = typeof params.company === "string" ? params.company : null;
  const view = await loadView(authOutcome, requestedCompany);

  if (view.kind === "not_configured") {
    return <LandingPage notice={{ text: NOT_CONFIGURED_MESSAGE, role: "status" }} />;
  }
  if (view.kind === "signed_out") {
    const message = authOutcomeMessage(view.authOutcome);
    return <LandingPage notice={message ? { text: message, role: "alert" } : undefined} />;
  }
  return (
    <>
      <SiteHeader variant="workspace" />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-5 py-16 sm:px-8">
        <header className="flex flex-col gap-2">
          <h1 className="text-3xl font-extrabold tracking-tight">
            <AppName />
          </h1>
          <DemoNotice />
        </header>
        <CompanyWorkspace view={view} />
      </main>
      <SiteFooter linked={false} />
    </>
  );
}

async function loadView(authOutcome: string | null, requestedCompany: string | null): Promise<WorkspaceView> {
  const configured = readAuthConfig();
  if (!configured.ok) return { kind: "not_configured" };
  const session = await readSession(configured.config);
  if (session === null) return { kind: "signed_out", authOutcome };
  const overview = await getCompanyOverview(session.accessToken, configured.config, requestedCompany);
  if (!overview.ok) return { kind: "error", failure: overview.failure };
  const { companies, selected } = overview.data;
  if (selected === null) return { kind: "choose", choices: companies };
  return { kind: "signed_in", ...selected, choices: companies };
}
