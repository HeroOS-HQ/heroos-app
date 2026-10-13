/**
 * HeroOS logo: JJ's original symbol (public/branding/heroos-logo-symbol.svg,
 * used unchanged) beside live wordmark text. The full official wordmark file
 * is still to come; when it arrives, swap this one component and every header
 * and footer follows. The symbol is decorative because the text names the brand.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`}>
      {/* A plain <img>: next/image adds an inline style attribute that the CSP forbids, and a static SVG gains nothing from optimization. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img alt="" aria-hidden="true" className="size-10" height={40} src="/branding/heroos-logo-symbol.svg" width={40} />
      <span className="text-2xl font-extrabold tracking-tight text-hero-navy">
        Hero<span className="text-hero-blue">OS</span>
      </span>
    </span>
  );
}
