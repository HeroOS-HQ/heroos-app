import { notFound } from "next/navigation";
import { Suspense } from "react";

import { FinalScreen } from "../../_mockup/final";
import { isFinalState } from "../../_mockup/final-scenario";

/** One state of the final Page 1 workspace. `?clean=1` hides the review bar. */
export default function FinalAskHeroOSState({ params, searchParams }: PageProps<"/design-review/oct20/final/[state]">) {
  return (
    <Suspense fallback={null}>
      <Final params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Final({ params, searchParams }: PageProps<"/design-review/oct20/final/[state]">) {
  const { state } = await params;
  const query = await searchParams;
  if (!isFinalState(state)) notFound();
  return <FinalScreen clean={query.clean === "1"} state={state} />;
}
