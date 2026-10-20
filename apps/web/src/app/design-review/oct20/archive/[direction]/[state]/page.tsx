import { notFound } from "next/navigation";
import { Suspense } from "react";

import { DirectionA } from "../../../_mockup/direction-a";
import { DirectionB } from "../../../_mockup/direction-b";
import { ReviewBar } from "../../../_mockup/parts";
import { isDirection, isState } from "../../../_mockup/scenario";

/** Round 1 (archived reference): one state of Direction A or B. `?clean=1` hides the review bar; `?rail=0` collapses B's case rail. */
export default function AskHeroOSMockup({ params, searchParams }: PageProps<"/design-review/oct20/archive/[direction]/[state]">) {
  return (
    <Suspense fallback={null}>
      <Mockup params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Mockup({ params, searchParams }: PageProps<"/design-review/oct20/archive/[direction]/[state]">) {
  const { direction, state } = await params;
  const query = await searchParams;
  if (!isDirection(direction) || !isState(state)) notFound();
  const opts = { clean: query.clean === "1", rail: query.rail !== "0" };
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {opts.clean ? null : <ReviewBar direction={direction} opts={opts} state={state} />}
      {direction === "a" ? <DirectionA opts={opts} state={state} /> : <DirectionB opts={opts} state={state} />}
    </div>
  );
}
