import { Suspense } from "react";

import { AppName } from "@/components/app-name";
import { CompanyWorkspace, type WorkspaceView } from "@/components/company-workspace";
import { readAuthConfig } from "@/lib/server/config";
import { getCompanyOverview } from "@/lib/server/heroos-api";
import { readSession } from "@/lib/server/session";

const AUTH_OUTCOMES = new Set(["failed", "cancelled", "expired", "unavailable"]);

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          <AppName />
        </h1>
        <p className="text-sm text-zinc-600">
          Temporary demonstration environment. All data is synthetic.
        </p>
      </header>
      <Suspense fallback={<p className="text-zinc-600">Loading…</p>}>
        <Workspace searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Workspace({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const params = await searchParams;
  const rawOutcome = typeof params.auth === "string" ? params.auth : null;
  const authOutcome = rawOutcome !== null && AUTH_OUTCOMES.has(rawOutcome) ? rawOutcome : null;
  // Only a hint: it is used solely to pick among Companies the API has authorized.
  const requestedCompany = typeof params.company === "string" ? params.company : null;
  return <CompanyWorkspace view={await loadView(authOutcome, requestedCompany)} />;
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
