import { redirect } from "next/navigation";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";

/**
 * Retired (M2-NEW-02): the Conduct & Discipline overview. Its cases are in the
 * Cases drawer of Ask HeroOS, which this opens.
 * Kept so saved links still land somewhere useful; the target authorizes the
 * Company id like every page.
 */
export default function RetiredPage({ params }: PageProps<"/workspaces/[companyId]/disciplinary">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <ToAsk params={params} />
    </Suspense>
  );
}

async function ToAsk({ params }: Pick<PageProps<"/workspaces/[companyId]/disciplinary">, "params">): Promise<null> {
  const { companyId } = await params;
  redirect(`/workspaces/${encodeURIComponent(companyId)}?cases=open`);
}
