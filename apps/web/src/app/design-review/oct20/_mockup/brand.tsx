/**
 * JJ's preferred logo candidate (sent 20 Oct 2026), for the design review only.
 * The production BrandMark (components/site/brand-mark.tsx) is unchanged.
 *
 * The image is a transparent derivative of JJ's JPEG: the artwork's pixels
 * are copied exactly; only the light grey square behind it was made
 * transparent (and its anti-aliased rim given matching transparency), then
 * cropped to the mark's own square. Never redrawn, recoloured or reshaped.
 * The existing "HeroOS" wordmark stays beside it: the new logo is a symbol.
 */

export const LOGO_CANDIDATE = "/design-review/oct20/heroos-logo-candidate.png";

/** The HeroOS symbol alone, filling the box its caller sizes (square). */
export function LogoSymbol({ className }: { className: string }) {
  return (
    // Plain <img>: next/image adds an inline style attribute that the CSP forbids.
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className={`shrink-0 ${className}`} height={512} src={LOGO_CANDIDATE} width={512} />
  );
}

/** Symbol + wordmark at one height (the same sizes as the production BrandMark). */
export function CandidateBrandMark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-0.5 sm:gap-1 ${className ?? ""}`}>
      <span className="sr-only">HeroOS</span>
      <LogoSymbol className="size-5 min-[360px]:size-[1.625rem] sm:size-8" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="h-5 w-auto shrink-0 min-[360px]:h-[1.625rem] sm:h-8"
        height={144}
        src="/branding/heroos-logo-wordmark.png"
        width={480}
      />
    </span>
  );
}
