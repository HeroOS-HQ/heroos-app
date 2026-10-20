import { redirect } from "next/navigation";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";

/**
 * Retired (M2-NEW-02): HR Services is no longer a page of its own. Ask HeroOS is
 * where every HR question starts.
 * Kept so saved links still land somewhere useful; the target authorizes the
 * Company id like every page.
 */
export default function RetiredPage({ params }: PageProps<"/workspaces/[companyId]/hr-services">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <ToAsk params={params} />
    </Suspense>
  );
}

async function ToAsk({ params }: Pick<PageProps<"/workspaces/[companyId]/hr-services">, "params">): Promise<null> {
  const { companyId } = await params;
  redirect(`/workspaces/${encodeURIComponent(companyId)}`);
}
