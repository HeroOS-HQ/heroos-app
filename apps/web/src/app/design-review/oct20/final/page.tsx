import { Suspense } from "react";

import { FinalScreen } from "../_mockup/final";

/** Final Page 1, Ask HeroOS: the default signed-in experience (empty state). `?clean=1` hides the review bar. */
export default function FinalAskHeroOS({ searchParams }: PageProps<"/design-review/oct20/final">) {
  return (
    <Suspense fallback={null}>
      <Final searchParams={searchParams} />
    </Suspense>
  );
}

async function Final({ searchParams }: Pick<PageProps<"/design-review/oct20/final">, "searchParams">) {
  const query = await searchParams;
  return <FinalScreen clean={query.clean === "1"} state="empty" />;
}
