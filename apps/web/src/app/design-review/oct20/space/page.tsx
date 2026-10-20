import { Suspense } from "react";

import { SpaceScreen } from "../_mockup/space";

/** Page 3, Company Space (full-access state). `?clean=1` hides the review bar. */
export default function CompanySpace({ searchParams }: PageProps<"/design-review/oct20/space">) {
  return (
    <Suspense fallback={null}>
      <Space searchParams={searchParams} />
    </Suspense>
  );
}

async function Space({ searchParams }: Pick<PageProps<"/design-review/oct20/space">, "searchParams">) {
  const query = await searchParams;
  return <SpaceScreen clean={query.clean === "1"} state="full" />;
}
