import type { ReactNode } from "react";

import { LogoSymbol } from "@/components/site/brand-mark";
import {
  BuildingIcon,
  CertificateIcon,
  CheckIcon,
  SparkleIcon,
} from "@/components/site/icons";

type SceneStage = "company" | "licensing" | "review" | "complete";

/**
 * Hannah beside each setup stage (JJ design review, screens 02–05). JJ's
 * approved front-view artwork, unchanged and never animated, stands in a soft
 * sky with a quiet skyline drawn in the brand's light blue. The review
 * mockups show her in other poses (pointing, holding a licence or a tablet,
 * cheering with a laptop); no approved artwork exists for those yet, so a
 * small prop beside her and the speech bubble change by stage instead.
 * Everything here is decorative and hidden from assistive technology except
 * the guidance card passed as `children`.
 */
export function HannahOnboardingScene({
  stage,
  bubble,
  children,
}: {
  stage: SceneStage;
  bubble: string;
  children?: ReactNode;
}) {
  return (
    <div className="absolute inset-0">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <SceneBackdrop />
        {/* Hannah, full length, feet near the action bar; the prop rides beside her. */}
        {/* Sized by the window: wider screens give her more room, shorter ones keep the bubble clear of her. */}
        <div className="absolute bottom-[2.5%] left-[30%] w-[clamp(13rem,min(calc(17rem_+_(100vw_-_80rem)_*_0.44),calc((100dvh_-_28.75rem)_/_1.5)),24rem)] -translate-x-1/2">
          <span className="absolute -inset-x-[12%] bottom-[-2%] top-[18%] rounded-full bg-[radial-gradient(closest-side,rgb(255_255_255/0.85),rgb(255_255_255/0))]" />
          {/* Plain <img>: next/image adds an inline style attribute that the CSP forbids. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt=""
            className="relative h-auto w-full max-w-none drop-shadow-[0_14px_22px_rgb(14_30_61/0.16)]"
            height={900}
            src="/branding/hannah-hero-front.webp"
            width={600}
          />
          {/* The prop needs room beside her: wide screens only. */}
          <span className="hidden 2xl:block">
            <StageProp stage={stage} />
          </span>
        </div>
      </div>
      <p
        aria-hidden="true"
        className="pointer-events-none absolute left-[4%] top-4 w-[12.5rem] -rotate-[6deg] rounded-[2.5rem] border-2 border-hero-yellow bg-white px-5 py-4 text-center text-[1.0625rem] font-extrabold italic leading-snug text-hero-navy shadow-[0_10px_24px_-16px_rgb(14_30_61/0.4)] 2xl:left-[6%] 2xl:top-5 2xl:w-[14.5rem] 2xl:px-6 2xl:text-[1.25rem]"
      >
        {bubble}
        <span className="mx-auto mt-2 block h-1 w-14 rounded-full bg-hero-yellow" />
        <span className="absolute -bottom-[0.6rem] right-12 size-4 rotate-45 border-b-2 border-r-2 border-hero-yellow bg-white" />
      </p>
      <div className="absolute right-5 top-4 z-10 w-[16rem] 2xl:right-7 2xl:top-6 2xl:w-[18.5rem]">{children}</div>
    </div>
  );
}

/** Sky, sun, a two-depth skyline with one tall tower, and the ground: brand tints only. */
function SceneBackdrop() {
  return (
    <>
      <div className="absolute inset-0 bg-[linear-gradient(180deg,#fdf6e3_0%,#eef3fb_52%,#f6efdc_100%)] [mask-image:linear-gradient(90deg,transparent_0%,black_16%)]" />
      <div className="absolute -right-24 -top-28 size-[30rem] rounded-full bg-hero-yellow/10" />
      <div className="absolute right-[30%] top-[10%] size-28 rounded-full bg-hero-yellow/25 blur-2xl" />
      <div className="absolute inset-x-0 bottom-[8%] flex h-[46%] items-end justify-end gap-[0.3rem] pr-[2%] opacity-60 [mask-image:linear-gradient(90deg,transparent_0%,black_45%)]">
        <span className="h-[30%] w-10 rounded-t-md bg-hero-light-blue/15" />
        <span className="h-[46%] w-6 rounded-t-md bg-hero-light-blue/15" />
        <span className="h-[38%] w-9 rounded-t-lg bg-hero-light-blue/15" />
        <span className="h-[58%] w-5 rounded-t-md bg-hero-light-blue/20" />
        <span className="h-[34%] w-11 rounded-t-lg bg-hero-light-blue/15" />
        <span className="h-[52%] w-7 rounded-t-md bg-hero-light-blue/20" />
        <span className="h-[42%] w-8 rounded-t-md bg-hero-light-blue/15" />
        <span className="h-[64%] w-6 rounded-t-md bg-hero-light-blue/20" />
        <span className="h-[30%] w-10 rounded-t-lg bg-hero-light-blue/15" />
      </div>
      <div className="absolute inset-x-0 bottom-[8%] flex h-[62%] items-end justify-end gap-[0.4rem] pr-[4%] opacity-70 [mask-image:linear-gradient(90deg,transparent_0%,black_42%)]">
        <span className="h-[28%] w-9 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.28),rgb(88_136_232/0.14))]" />
        <span className="h-[42%] w-6 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.32),rgb(88_136_232/0.16))]" />
        <span className="h-[36%] w-10 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.28),rgb(88_136_232/0.14))]" />
        <span className="h-[50%] w-8 rounded-t-lg bg-[linear-gradient(180deg,rgb(88_136_232/0.32),rgb(88_136_232/0.16))]" />
        <span className="h-[40%] w-7 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.3),rgb(88_136_232/0.16))]" />
        {/* The tall tower: a tapering silhouette. */}
        <span className="h-full w-9 bg-[linear-gradient(180deg,rgb(88_136_232/0.48),rgb(88_136_232/0.22))] [clip-path:polygon(47%_0,53%_0,64%_38%,78%_62%,100%_100%,0_100%,22%_62%,36%_38%)]" />
        <span className="h-[56%] w-7 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.36),rgb(88_136_232/0.18))]" />
        <span className="h-[34%] w-9 rounded-t-lg bg-[linear-gradient(180deg,rgb(88_136_232/0.28),rgb(88_136_232/0.14))]" />
        <span className="h-[46%] w-6 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.32),rgb(88_136_232/0.16))]" />
      </div>
      <div className="absolute inset-x-0 bottom-0 h-[8.5%] bg-[linear-gradient(180deg,#f4e9c8_0%,#faf3de_100%)] [mask-image:linear-gradient(90deg,transparent_0%,black_22%)]" />
      <div className="absolute inset-x-0 bottom-[8.5%] h-px bg-white/90 [mask-image:linear-gradient(90deg,transparent_0%,black_30%)]" />
    </>
  );
}

/** Three short yellow strokes, the mockups' "spark" marks. */
function Sparks({ className }: { className: string }) {
  return (
    <span className={`absolute flex flex-col gap-1.5 ${className}`}>
      <span className="h-1 w-5 -rotate-[30deg] rounded-full bg-hero-yellow" />
      <span className="h-1 w-6 rounded-full bg-hero-yellow" />
      <span className="h-1 w-5 rotate-[30deg] rounded-full bg-hero-yellow" />
    </span>
  );
}

const line = "block h-1.5 rounded-full bg-[#e2e7f0]";

/** A prop beside Hannah for the stage (the mockups' pointing, licence, blueprint and laptop poses). */
function StageProp({ stage }: { stage: SceneStage }) {
  switch (stage) {
    case "company":
      return (
        <>
          <span className="absolute -right-[3.5rem] bottom-[16%] w-[5.5rem] rotate-[7deg] rounded-xl border border-[#e7e3d6] bg-white p-2.5 shadow-[0_10px_20px_-12px_rgb(14_30_61/0.35)] 2xl:-right-[3rem] 2xl:w-[7rem] 2xl:p-3">
            <span className="mx-auto flex size-9 items-center justify-center rounded-full bg-hero-yellow-tint text-hero-navy 2xl:size-11">
              <BuildingIcon className="size-5 2xl:size-6" />
            </span>
            <span className={`${line} mt-2 w-full`} />
            <span className={`${line} mt-1.5 w-2/3`} />
          </span>
          <Sparks className="-right-[4.5rem] bottom-[33%] rotate-[-20deg] 2xl:-right-[5.5rem]" />
        </>
      );
    case "licensing":
      return (
        <>
          <span className="absolute -right-[3.75rem] bottom-[15%] w-[6rem] rotate-[11deg] rounded-lg border border-[#e7e3d6] bg-white px-2.5 pb-3 pt-2.5 shadow-[0_10px_20px_-12px_rgb(14_30_61/0.35)] 2xl:-right-[3.5rem] 2xl:w-[7.75rem] 2xl:px-3">
            <CertificateIcon className="size-6 text-hero-navy 2xl:size-7" />
            <span className={`${line} mt-2 w-full`} />
            <span className={`${line} mt-1.5 w-5/6`} />
            <span className={`${line} mt-1.5 w-2/3`} />
            <span className="absolute -bottom-2.5 -right-2.5 size-7 rounded-full border-[3px] border-white bg-hero-yellow 2xl:size-8" />
          </span>
          <Sparks className="-right-[4.75rem] bottom-[36%] rotate-[-18deg] 2xl:-right-[5.75rem]" />
        </>
      );
    case "review":
      return (
        <>
          <span className="absolute -right-[4rem] bottom-[14%] w-[6.5rem] rotate-[9deg] rounded-xl border-[3px] border-hero-navy bg-white px-2.5 pb-3 pt-4 shadow-[0_10px_20px_-12px_rgb(14_30_61/0.35)] 2xl:-right-[3.75rem] 2xl:w-[8.25rem] 2xl:px-3">
            <span className="absolute -top-2 left-1/2 h-3 w-9 -translate-x-1/2 rounded-md bg-hero-navy" />
            {[0, 1, 2].map((row) => (
              <span className="mt-1.5 flex items-center gap-1.5 first:mt-0" key={row}>
                <span className="inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-hero-success text-white 2xl:size-5">
                  <CheckIcon className="size-2.5 stroke-[3.5] 2xl:size-3" />
                </span>
                <span className={`${line} flex-1`} />
              </span>
            ))}
          </span>
          <Sparks className="-right-[5rem] bottom-[36%] rotate-[-18deg] 2xl:-right-[6rem]" />
        </>
      );
    case "complete":
      return (
        <>
          <span className="absolute -right-[4.5rem] bottom-[14%] w-[7rem] -rotate-[9deg] 2xl:-right-[4.5rem] 2xl:w-[9rem]">
            <span className="flex h-[4.25rem] items-center justify-center rounded-t-lg border-[3px] border-[#c4cddd] bg-white shadow-[0_10px_20px_-12px_rgb(14_30_61/0.35)] 2xl:h-[5.5rem]">
              <LogoSymbol className="size-10 2xl:size-14" />
            </span>
            <span className="-mx-[8%] block h-2 rounded-b-md bg-[#c4cddd]" />
          </span>
          <SparkleIcon className="absolute -left-[0.5rem] top-[4%] size-8 text-hero-yellow 2xl:size-10" />
          <SparkleIcon className="absolute -left-[2rem] top-[24%] size-6 text-hero-yellow 2xl:size-7" />
          <Sparks className="-right-[5.25rem] bottom-[34%] rotate-[-18deg] 2xl:-right-[6.5rem]" />
        </>
      );
  }
}
