import { Suspense } from "react";

import { BlueprintScreen } from "../_mockup/blueprint";

/** Page 2, Company Blueprint (review state). `?clean=1` hides the review bar. */
export default function CompanyBlueprint({ searchParams }: PageProps<"/design-review/oct20/blueprint">) {
  return (
    <Suspense fallback={null}>
      <Blueprint searchParams={searchParams} />
    </Suspense>
  );
}

async function Blueprint({ searchParams }: Pick<PageProps<"/design-review/oct20/blueprint">, "searchParams">) {
  const query = await searchParams;
  return <BlueprintScreen clean={query.clean === "1"} state="review" />;
}
