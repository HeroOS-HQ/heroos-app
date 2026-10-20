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
