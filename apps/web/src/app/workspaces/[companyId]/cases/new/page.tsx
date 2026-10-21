import { redirect } from "next/navigation";
import { Suspense } from "react";

import { LoadingView } from "@/components/app/loading-view";

/**
 * Retired (M2-NEW-02): the New case form (a title first). A question in Ask
 * HeroOS opens a case now, without a title to type.
 * Kept so saved links still land somewhere useful; the target authorizes the
 * Company id like every page.
 */
export default function RetiredPage({ params }: PageProps<"/workspaces/[companyId]/cases/new">) {
  return (
    <Suspense fallback={<LoadingView layout="full" />}>
      <ToAsk params={params} />
    </Suspense>
  );
}

async function ToAsk({ params }: Pick<PageProps<"/workspaces/[companyId]/cases/new">, "params">): Promise<null> {
  const { companyId } = await params;
  redirect(`/workspaces/${encodeURIComponent(companyId)}`);
}
