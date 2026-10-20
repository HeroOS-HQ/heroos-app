import { notFound } from "next/navigation";
import { Suspense } from "react";

import { BlueprintScreen } from "../../_mockup/blueprint";
import { isBlueprintState } from "../../_mockup/blueprint-scenario";

/** One state of Page 2, Company Blueprint. `?clean=1` hides the review bar. */
export default function CompanyBlueprintState({ params, searchParams }: PageProps<"/design-review/oct20/blueprint/[state]">) {
  return (
    <Suspense fallback={null}>
      <Blueprint params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Blueprint({ params, searchParams }: PageProps<"/design-review/oct20/blueprint/[state]">) {
  const { state } = await params;
  const query = await searchParams;
  if (!isBlueprintState(state)) notFound();
  return <BlueprintScreen clean={query.clean === "1"} state={state} />;
}
