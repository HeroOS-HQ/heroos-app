import type { ReactNode, Ref } from "react";

import { CheckIcon, LightbulbIcon } from "@/components/site/icons";

import { OnboardingProgress, type StageKey, STAGES, stageNumber } from "./onboarding-progress";
import { HannahOnboardingScene } from "./onboarding-scene";

/**
 * The founder setup journey's own frame (JJ design review, screens 01–05),
 * used by /onboarding and the ready page only: a full-width canvas below the
 * app header, the six-stage progress, a white card on the left, Hannah's
 * scene with a guidance card on the right, and an action bar along the bottom
 * (sticky on wide screens). Smaller screens stack: card, actions, guidance.
 */

const focusRing = "focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue";

/** Yellow call to action with navy text (the brand's primary button), in the review screens' squarer shape. */
export const onboardingPrimary = `inline-flex min-h-[3.25rem] items-center justify-center gap-2.5 rounded-[0.875rem] bg-hero-yellow px-7 text-base font-bold text-hero-navy shadow-[0_8px_20px_-12px_rgb(255_212_1/0.95)] transition-[box-shadow,transform,background-color] duration-200 hover:-translate-y-px hover:bg-[#f6cb00] disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

export const onboardingSecondary = `inline-flex min-h-[3.25rem] items-center justify-center gap-2.5 rounded-[0.875rem] border border-[#c3cad6] bg-white px-7 text-base font-bold text-hero-navy transition-colors duration-200 hover:bg-hero-blue-tint disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

/** A small blue text action (Edit, Open), never under the 44 px target size. */
export const onboardingLink = `inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg px-1 text-[0.9375rem] font-bold text-hero-blue-ink underline underline-offset-4 hover:text-hero-navy disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

/** Page gutter of the journey (aligned with the header's logo on wide screens). */
export const onboardingGutter = "px-4 sm:px-8 xl:px-14";

/**
 * The canvas: at least the window's height below the header, so the action
 * bar rests on the bottom edge, with a quiet warm backdrop. `overflow-clip`
 * (not hidden: no scroll container) keeps the decoration in bounds without
 * breaking `sticky`.
 */
export function OnboardingCanvas({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate flex min-h-[calc(100dvh-4.0625rem)] flex-col overflow-clip sm:min-h-[calc(100dvh-4.5625rem)]">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -right-[12rem] -top-[14rem] size-[44rem] rounded-full bg-[#fbefc4]/45" />
        <div className="absolute -bottom-[16rem] -left-[10rem] size-[36rem] rounded-full bg-[#fbefc4]/35" />
        <div className="absolute inset-x-0 top-0 h-48 bg-[linear-gradient(180deg,rgb(255_255_255/0.7),transparent)]" />
      </div>
      {children}
    </div>
  );
}

/** The heading's last words on a yellow highlighter band (navy text: yellow text on white can't be read). */
export function AccentTitle({
  lead,
  accent,
  headingRef,
  id,
  className,
}: {
  lead: string;
  accent: string;
  headingRef?: Ref<HTMLHeadingElement>;
  id: string;
  className?: string;
}) {
  return (
    <h1
      className={`break-words font-extrabold text-hero-navy focus-visible:outline-none ${className ?? ""}`}
      id={id}
      ref={headingRef}
      tabIndex={-1}
    >
      {lead}{" "}
      <span className="bg-[linear-gradient(180deg,transparent_58%,rgb(255_212_1/0.95)_58%,rgb(255_212_1/0.95)_90%,transparent_90%)] px-0.5 [box-decoration-break:clone]">
        {accent}
      </span>
    </h1>
  );
}

/** The white card of a stage: "STEP N OF 6", the heading, an introduction, then the stage's content. */
export function StageCard({
  stage,
  lead,
  accent,
  intro,
  headingRef,
  children,
}: {
  stage: StageKey;
  lead: string;
  accent: string;
  intro: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby="onboarding-heading"
      className="h-full rounded-[1.25rem] border border-hero-border/70 bg-white px-5 pb-7 pt-6 shadow-[0_1px_2px_rgb(14_30_61/0.04),0_14px_36px_-18px_rgb(14_30_61/0.2)] sm:px-7 sm:pb-7 sm:pt-7"
    >
      <p className="text-[0.9375rem] font-semibold uppercase tracking-[0.05em] text-hero-muted">
        Step {stageNumber(stage)} of {STAGES.length}
      </p>
      <AccentTitle
        accent={accent}
        className="mt-1.5 text-[2rem] leading-[1.1] tracking-[-0.03em] sm:text-[2.5rem] xl:text-[clamp(2.5rem,3vw,2.875rem)]"
        headingRef={headingRef}
        id="onboarding-heading"
        lead={lead}
      />
      <div className="mt-2.5 max-w-[44rem] text-base leading-[1.5] text-hero-muted sm:text-[1.0625rem]">{intro}</div>
      {children}
    </section>
  );
}

/** "Why we need this information" and similar: factual notes beside the form, never legal advice. */
export function GuidanceCard({
  title,
  items,
  numbered = false,
}: {
  title: string;
  items: ReactNode[];
  numbered?: boolean;
}) {
  return (
    <section className="rounded-[1.125rem] border border-white/80 bg-white/90 px-4 pb-5 pt-4 2xl:px-5 shadow-[0_10px_30px_-18px_rgb(14_30_61/0.3)] backdrop-blur-sm">
      <h2 className="flex items-center gap-2 text-[0.9375rem] font-extrabold text-hero-navy">
        <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-hero-yellow-tint text-hero-navy">
          <LightbulbIcon className="size-[1.125rem]" />
        </span>
        {title}
      </h2>
      <ol className="mt-3 flex flex-col gap-3">
        {items.map((item, position) => (
          <li className="flex items-start gap-3 text-[0.9375rem] leading-snug text-hero-navy/85" key={position}>
            <span
              aria-hidden="true"
              className="mt-px inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-hero-yellow text-[0.8125rem] font-extrabold text-hero-navy"
            >
              {numbered ? position + 1 : <CheckIcon className="size-3.5 stroke-[3]" />}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * The bottom action bar: Back on the left; the next step (and leaving) on the
 * right. Sticky on wide screens; on phones it sits after the form so the
 * on-screen keyboard can never cover it.
 */
export function ActionBar({ start, end }: { start?: ReactNode; end: ReactNode }) {
  return (
    <div className="bottom-0 z-30 border-t border-hero-border bg-white/95 backdrop-blur-md lg:sticky">
      <div
        className={`flex flex-col-reverse gap-3 py-4 sm:flex-row sm:items-center sm:justify-between lg:min-h-[5.25rem] lg:py-3.5 ${onboardingGutter}`}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">{start}</div>
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">{end}</div>
      </div>
    </div>
  );
}

type SceneStage = Exclude<StageKey, "welcome">;

/**
 * One stage of the journey after Welcome: progress, an optional notice, the
 * card beside Hannah's scene, the action bar, and on smaller screens the
 * guidance after the actions (shown once at any width).
 */
export function OnboardingStage({
  stage,
  bubble,
  guidance,
  notice,
  actions,
  children,
}: {
  stage: SceneStage;
  bubble: string;
  guidance: ReactNode;
  notice?: ReactNode;
  actions: ReactNode;
  children: ReactNode;
}) {
  return (
    <OnboardingCanvas>
      <OnboardingProgress current={stage} />
      {notice ? <div className={`pb-3 ${onboardingGutter}`}>{notice}</div> : null}
      <div className="grid flex-1 px-4 sm:px-8 xl:grid-cols-[minmax(0,min(52.5rem,57%))_minmax(0,1fr)] xl:pl-14 xl:pr-0">
        <div className="min-w-0 pb-6 xl:pb-5">{children}</div>
        {/* The scene stays in view while a long stage scrolls: below the header, above the action bar. */}
        <div className="relative hidden xl:block">
          <div className="sticky top-[4.5625rem] h-[calc(100dvh-16.25rem)] max-h-full min-h-[34rem]">
            <HannahOnboardingScene bubble={bubble} stage={stage}>
              {guidance}
            </HannahOnboardingScene>
          </div>
        </div>
      </div>
      {actions}
      <div className={`pb-10 pt-6 xl:hidden ${onboardingGutter}`}>
        <div className="max-w-[44rem]">{guidance}</div>
      </div>
    </OnboardingCanvas>
  );
}
