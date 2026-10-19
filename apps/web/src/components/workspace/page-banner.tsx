import type { ReactNode } from "react";

import { ChevronRightIcon } from "@/components/site/icons";

/** Page padding of the company pages (full width beside the navigation). */
export const pageGutter = "px-4 sm:px-6 lg:px-[1.5625rem]";

/**
 * Hannah greeting from the top right of a company page (JJ design review,
 * screens 06–09): JJ's approved front-view artwork, unchanged and never
 * animated, in a soft sky with a sun and a quiet skyline drawn in the brand's
 * light blue. Decorative only, so hidden from assistive technology. The
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
        {/* Sky, fading into the page on the left. */}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#e1ecfc_0%,#eef3fb_50%,#fbf4e0_100%)] [mask-image:linear-gradient(90deg,transparent_0%,black_30%)]" />
        <div className="absolute right-[4%] top-[8%] size-40 rounded-full bg-hero-yellow/35 blur-2xl" />
        {/* A quiet skyline. */}
        <div className="absolute inset-x-0 bottom-0 flex h-[82%] items-end justify-end gap-[0.4rem] pr-[2%] [mask-image:linear-gradient(90deg,transparent_0%,black_40%)]">
          <span className="h-[30%] w-8 rounded-t-md bg-hero-light-blue/20" />
          <span className="h-[48%] w-5 rounded-t-md bg-hero-light-blue/25" />
          <span className="h-[38%] w-9 rounded-t-lg bg-hero-light-blue/20" />
          <span className="h-[62%] w-6 rounded-t-md bg-hero-light-blue/30" />
          <span className="h-[44%] w-8 rounded-t-md bg-hero-light-blue/20" />
          <span className="h-[96%] w-3 rounded-t-full bg-hero-light-blue/35" />
          <span className="h-[56%] w-6 rounded-t-md bg-hero-light-blue/25" />
          <span className="h-[40%] w-10 rounded-t-lg bg-hero-light-blue/20" />
          <span className="h-[70%] w-5 rounded-t-md bg-hero-light-blue/30" />
          <span className="h-[34%] w-9 rounded-t-lg bg-hero-light-blue/20" />
        </div>
        <div className="absolute inset-x-0 bottom-0 h-[14%] bg-[linear-gradient(180deg,transparent,#fbf1d6)]" />
        {/* Hannah, from the waist up. Plain <img>: next/image adds an inline style the CSP forbids. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          alt=""
          className="absolute right-[13%] top-[0.5rem] h-auto w-[clamp(12rem,44%,18.5rem)] max-w-none drop-shadow-[0_10px_18px_rgb(14_30_61/0.16)]"
          height={900}
          src="/branding/hannah-hero-front.webp"
          width={600}
        />
      </div>
      <p
        className={`absolute top-[12%] w-[14rem] -rotate-[5deg] rounded-[2.5rem] border-2 border-hero-yellow bg-white px-6 py-3.5 text-center text-[1.0625rem] font-extrabold italic leading-snug text-hero-navy shadow-[0_8px_22px_-14px_rgb(14_30_61/0.35)] ${
          bubbleOut ? "-left-[5rem]" : "right-[calc(13%_+_clamp(9.5rem,36%,15rem))]"
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
