/**
 * HeroOS's approved symbol: JJ's logo from the Oct 20 design package (PR #52,
 * `public/design-review/oct20`), copied byte for byte to
 * `/branding/heroos-symbol.png`. Never redrawn, recoloured or reshaped.
 */
export const HEROOS_SYMBOL = "/branding/heroos-symbol.png";

/** The symbol alone, filling the square box its caller sizes. */
export function LogoSymbol({ className }: { className: string }) {
  return (
    // Plain <img>: next/image adds an inline style attribute that the CSP forbids.
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className={`shrink-0 ${className}`} height={512} src={HEROOS_SYMBOL} width={512} />
  );
}

/**
 * HeroOS's logo: the symbol and the "HeroOS" wordmark at one height. One logo
 * everywhere: the public site's header and footer and every signed-in top bar
 * (the workspace header and `AppShell`). The favicon and app icons are
 * separate files.
 */
export function BrandMark({ className }: { className?: string }) {
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
