import { notFound } from "next/navigation";
import { Suspense } from "react";

import { SpaceScreen } from "../../_mockup/space";
import { isSpaceState } from "../../_mockup/space-scenario";

/** One state of Page 3, Company Space. `?clean=1` hides the review bar. */
export default function CompanySpaceState({ params, searchParams }: PageProps<"/design-review/oct20/space/[state]">) {
  return (
    <Suspense fallback={null}>
      <Space params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Space({ params, searchParams }: PageProps<"/design-review/oct20/space/[state]">) {
  const { state } = await params;
  const query = await searchParams;
  if (!isSpaceState(state)) notFound();
  return <SpaceScreen clean={query.clean === "1"} state={state} />;
}
