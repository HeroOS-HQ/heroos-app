import { redirect } from "next/navigation";
import { Suspense } from "react";

import { LandingPage } from "@/components/site/landing-page";
import { SiteHeader } from "@/components/site/site-header";
import { authOutcomeMessage, NOT_CONFIGURED_MESSAGE } from "@/lib/messages";
import { sessionGate } from "@/lib/server/app-state";

/**
 * Public homepage for signed-out visitors (with "Get started" and "Sign in").
 * A signed-in visitor goes to their workspaces, which the API discovers.
 */
export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<SiteHeader variant="workspace" />}>
      <HomeContent searchParams={searchParams} />
    </Suspense>
  );
}

async function HomeContent({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const params = await searchParams;
  const outcome = typeof params.auth === "string" ? params.auth : null;
  const message = authOutcomeMessage(outcome);
  const gate = await sessionGate();
  if (gate.kind === "not_configured") {
    return <LandingPage notice={{ text: NOT_CONFIGURED_MESSAGE, role: "status" }} />;
  }
  if (gate.kind === "signed_out") {
    return (
      <LandingPage
        notice={message ? { text: message, role: "alert", accountActions: outcome === "verify_email" } : undefined}
      />
    );
  }
  redirect("/workspaces");
}
