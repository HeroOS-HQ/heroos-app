/**
 * HeroOS's approved mark and standalone wordmark.
 *
 * The image files are transparent SVG traces of JJ's supplied artwork, in its
 * original colors; the backgrounds the artwork was supplied on are removed, so
 * the logo sits cleanly on the translucent sticky header. No logo shapes,
 * colors, or lettering were redrawn.
 *
 * Keep the logo shared so header, footer, and workspace branding stay in sync.
 * `compact` shows the mark alone on phones, for headers with no room for the
 * wordmark.
 */
export function BrandMark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 sm:gap-2.5 ${className ?? ""}`}>
      <span className="sr-only">HeroOS</span>
      {/* Plain <img>: next/image adds an inline style attribute that the CSP forbids, and a static SVG gains nothing from optimization. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="size-6 shrink-0 min-[360px]:size-8 sm:size-10"
        height={1200}
        src="/branding/heroos-mark-transparent.svg"
        width={1200}
      />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className={`h-3.5 w-auto shrink-0 min-[360px]:h-4.5 sm:h-5.5 ${compact ? "max-sm:hidden" : ""}`}
        height={185}
        src="/branding/heroos-wordmark-transparent.svg"
        width={950}
      />
    </span>
  );
}
