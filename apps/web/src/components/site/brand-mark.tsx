/**
 * HeroOS's approved logo: the speech-bubble symbol and the "HeroOS" wordmark.
 *
 * Both images are transparent cuts of the approved artwork (2026-10-20): the
 * design and colors are unchanged; only the white background was removed. They
 * share one height and the wordmark image starts where the symbol's ends, so
 * shown at the same height they reproduce the approved lockup, spacing
 * included.
 *
 * Keep the logo shared so header, footer, and workspace branding stay in sync.
 * `compact` shows the symbol alone on phones, for headers with no room for the
 * wordmark.
 */
export function BrandMark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={`inline-flex shrink-0 items-center ${className ?? ""}`}>
      <span className="sr-only">HeroOS</span>
      {/* Plain <img>: next/image adds an inline style attribute that the CSP forbids. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="h-5 w-auto shrink-0 min-[360px]:h-[1.625rem] sm:h-8"
        height={144}
        src="/branding/heroos-logo-symbol.png"
        width={212}
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className={`h-5 w-auto shrink-0 min-[360px]:h-[1.625rem] sm:h-8 ${compact ? "max-sm:hidden" : ""}`}
        height={144}
        src="/branding/heroos-logo-wordmark.png"
        width={480}
      />
    </span>
  );
}

/**
 * The signed-in workspace's symbol: JJ's approved logo from the Oct 20 design
 * package (PR #52, `public/design-review/oct20`), copied byte for byte to
 * `/branding/heroos-symbol.png`. Never redrawn, recoloured or reshaped. The
 * public site keeps the speech-bubble `BrandMark` above.
 */
export const WORKSPACE_SYMBOL = "/branding/heroos-symbol.png";

/** The workspace symbol alone, filling the square box its caller sizes. */
export function LogoSymbol({ className }: { className: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className={`shrink-0 ${className}`} height={512} src={WORKSPACE_SYMBOL} width={512} />
  );
}

/** Symbol + wordmark at one height, as in the approved signed-in header. */
export function WorkspaceBrandMark({ className }: { className?: string }) {
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
