import type { ReactNode } from "react";

import { ChevronRightIcon } from "@/components/site/icons";

/** Page padding of the company pages (full width beside the navigation). */
export const pageGutter = "px-4 sm:px-6 lg:px-[1.5625rem]";

/**
 * Hannah greeting from the top right of a company page (JJ design review,
 * screens 06–09): JJ's approved front-view artwork, unchanged and never
 * animated, in a soft sky with a sun, a quiet two-depth skyline drawn in the
 * brand's light blue and a waterfront. An abstract composition from the brand
 * palette, not the review mockups' watercolour Dubai painting (no such asset
 * exists yet). Decorative only, so hidden from assistive technology. The
 * caller positions it (`relative` with a height, or `absolute`); the speech
 * bubble may reach past its left edge (`bubbleOut`).
 */
export function HannahScene({
  bubble,
  className,
  bubbleOut = false,
}: {
  bubble: string;
  className?: string;
  bubbleOut?: boolean;
}) {
  return (
    <div aria-hidden="true" className={`pointer-events-none ${className ?? ""}`}>
      <div className="absolute inset-0 overflow-hidden">
        {/* A soft wash of sky and sand, fading into the page on the left. */}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#dfeafb_0%,#ecf2fb_46%,#f8f2e0_100%)] [mask-image:linear-gradient(90deg,transparent_0%,black_28%)]" />
        <div className="absolute -top-16 right-0 h-56 w-[70%] rounded-full bg-[#cfdff8]/60 blur-3xl" />
        <div className="absolute bottom-[18%] left-[30%] h-24 w-[45%] rounded-full bg-white/70 blur-2xl" />
        {/* The sun, with a glow. */}
        <div className="absolute right-[2%] top-[4%] size-40 rounded-full bg-hero-yellow/30 blur-2xl" />
        <div className="absolute right-[7%] top-[13%] size-14 rounded-full bg-[radial-gradient(circle,#ffe36b_0%,#ffd401_60%,transparent_72%)] opacity-70" />
        {/* A quiet skyline in two depths (brand light blue), with one tall tower. */}
        <div className="absolute inset-x-0 bottom-[11%] flex h-[70%] items-end justify-end gap-[0.3rem] pr-[1%] opacity-80 [mask-image:linear-gradient(90deg,transparent_0%,black_42%)]">
          <span className="h-[26%] w-10 rounded-t-md bg-hero-light-blue/15" />
          <span className="h-[40%] w-6 rounded-t-md bg-hero-light-blue/15" />
          <span className="h-[34%] w-9 rounded-t-lg bg-hero-light-blue/15" />
          <span className="h-[52%] w-5 rounded-t-md bg-hero-light-blue/20" />
          <span className="h-[30%] w-11 rounded-t-lg bg-hero-light-blue/15" />
          <span className="h-[46%] w-7 rounded-t-md bg-hero-light-blue/20" />
          <span className="h-[38%] w-8 rounded-t-md bg-hero-light-blue/15" />
          <span className="h-[58%] w-6 rounded-t-md bg-hero-light-blue/20" />
          <span className="h-[28%] w-10 rounded-t-lg bg-hero-light-blue/15" />
        </div>
        <div className="absolute inset-x-0 bottom-[11%] flex h-[88%] items-end justify-end gap-[0.4rem] pr-[2%] [mask-image:linear-gradient(90deg,transparent_0%,black_40%)]">
          <span className="h-[30%] w-9 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.3),rgb(88_136_232/0.16))]" />
          <span className="h-[46%] w-6 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.34),rgb(88_136_232/0.18))]" />
          <span className="h-[38%] w-10 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.3),rgb(88_136_232/0.16))]" />
          <span className="h-[54%] w-8 rounded-t-lg bg-[linear-gradient(180deg,rgb(88_136_232/0.34),rgb(88_136_232/0.18))]" />
          <span className="h-[42%] w-7 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.32),rgb(88_136_232/0.18))]" />
          <span className="h-[62%] w-5 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.38),rgb(88_136_232/0.2))]" />
          <span className="h-[48%] w-8 rounded-t-lg bg-[linear-gradient(180deg,rgb(88_136_232/0.34),rgb(88_136_232/0.18))]" />
          {/* The tall tower: a tapering silhouette, to Hannah's right. */}
          <span className="h-full w-8 bg-[linear-gradient(180deg,rgb(88_136_232/0.5),rgb(88_136_232/0.24))] [clip-path:polygon(47%_0,53%_0,64%_38%,78%_62%,100%_100%,0_100%,22%_62%,36%_38%)]" />
          <span className="h-[58%] w-7 rounded-t-md bg-[linear-gradient(180deg,rgb(88_136_232/0.38),rgb(88_136_232/0.2))]" />
          <span className="h-[36%] w-9 rounded-t-lg bg-[linear-gradient(180deg,rgb(88_136_232/0.3),rgb(88_136_232/0.16))]" />
        </div>
        {/* The waterfront. */}
        <div className="absolute inset-x-0 bottom-0 h-[12%] bg-[linear-gradient(180deg,#f6ecc8_0%,#fbf4de_100%)] [mask-image:linear-gradient(90deg,transparent_0%,black_30%)]" />
        <div className="absolute inset-x-0 bottom-[11%] h-px bg-white/80 [mask-image:linear-gradient(90deg,transparent_0%,black_40%)]" />
        {/* A soft halo so Hannah stands clear of the skyline. */}
        <div className="absolute right-[18%] top-[2%] h-[110%] w-[clamp(13rem,46%,19rem)] rounded-full bg-[radial-gradient(closest-side,rgb(255_255_255/0.85),rgb(255_255_255/0)_100%)]" />
        {/* Hannah, from the waist up: JJ's approved artwork, unchanged. Plain <img>: next/image adds an inline style the CSP forbids. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          alt=""
          className="absolute right-[20%] top-[0.5rem] h-auto w-[clamp(12rem,42%,17.5rem)] max-w-none drop-shadow-[0_10px_18px_rgb(14_30_61/0.16)]"
          height={900}
          src="/branding/hannah-hero-front.webp"
          width={600}
        />
      </div>
      <p
        className={`absolute top-[12%] w-[14rem] -rotate-[5deg] rounded-[2.5rem] border-2 border-hero-yellow bg-white px-6 py-3.5 text-center text-[1.0625rem] font-extrabold italic leading-snug text-hero-navy shadow-[0_8px_22px_-14px_rgb(14_30_61/0.35)] ${
          bubbleOut ? "-left-[5.5rem]" : "right-[calc(20%_+_15rem)]"
        }`}
      >
        {bubble}
        <span className="absolute -right-[0.45rem] bottom-6 size-4 rotate-45 border-r-2 border-t-2 border-hero-yellow bg-white" />
      </p>
    </div>
  );
}

export type Crumb = { label: string; href?: string };

/** Where this page sits (links for the levels above it; the current page is plain text). */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-1.5 text-[0.9375rem] text-hero-muted">
        {items.map((item, index) => (
          <li className="flex items-center gap-1.5" key={item.label}>
            {index > 0 ? <ChevronRightIcon className="size-4 shrink-0" /> : null}
            {item.href ? (
              <a
                className="inline-flex min-h-11 items-center rounded-md font-semibold text-hero-muted underline-offset-4 hover:text-hero-blue-ink hover:underline"
                href={item.href}
              >
                {item.label}
              </a>
            ) : (
              <span aria-current="page" className="inline-flex min-h-11 items-center font-bold text-hero-navy">
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * The top of a company page: where it sits, its title and a short
 * introduction on the left, Hannah on the right (wide screens).
 */
export function PageBanner({
  title,
  breadcrumbs,
  bubble,
  children,
}: {
  title: string;
  breadcrumbs?: Crumb[];
  bubble: string;
  children?: ReactNode;
}) {
  return (
    <div className="relative">
      <HannahScene bubble={bubble} className="absolute inset-y-0 right-0 hidden w-[52%] xl:block" />
      <div className={`relative ${pageGutter} pb-6 ${breadcrumbs ? "pt-3 sm:pt-4" : "pt-7 sm:pt-10"} xl:min-h-[13.25rem] xl:max-w-[52%] xl:pb-7`}>
        {breadcrumbs ? <Breadcrumbs items={breadcrumbs} /> : null}
        <h1 className="break-words text-[2rem] font-extrabold leading-[1.1] tracking-[-0.03em] text-hero-navy sm:text-[2.5rem] xl:text-[2.875rem]">
          {title}
        </h1>
        {children ? <div className="mt-3 text-base leading-relaxed text-hero-muted sm:text-[1.0625rem]">{children}</div> : null}
      </div>
    </div>
  );
}
