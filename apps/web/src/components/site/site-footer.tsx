import { BrandMark } from "./brand-mark";

const FOOTER_LINKS = [
  { label: "Home", href: "#top" },
  { label: "Explore HeroOS", href: "#how-it-works" },
  { label: "Platform", href: "#platform" },
];

/**
 * Decorative contour lines after the soft topographic waves in JJ's site
 * (design reference only). Generated once from a few sine terms, so the
 * markup is deterministic and the footer stays plain vector.
 */
const CONTOUR_LINES = Array.from({ length: 9 }, (_, line) => {
  const base = 56 + line * 11;
  const amplitude = 22 - line * 1.6;
  const points = Array.from({ length: 49 }, (_, step) => {
    const x = step * 25;
    const y =
      base +
      amplitude * Math.sin(step / 5.2 + line * 0.35) +
      amplitude * 0.45 * Math.sin(step / 2.4 + line * 0.6);
    return `${step === 0 ? "M" : "L"}${x} ${y.toFixed(1)}`;
  });
  return points.join(" ");
});

/**
 * `linked` shows the in-page links (landing only). Legal links are omitted
 * until real Privacy and Terms pages exist.
 */
export function SiteFooter({ linked = true }: { linked?: boolean }) {
  return (
    <footer className="relative overflow-hidden border-t border-hero-border bg-white">
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-40 w-full text-hero-light-blue"
        fill="none"
        preserveAspectRatio="none"
        viewBox="0 0 1200 160"
      >
        {CONTOUR_LINES.map((d, index) => (
          <path
            key={index}
            d={d}
            stroke="currentColor"
            strokeOpacity={0.1 + (index % 3) * 0.05}
            strokeWidth="1.25"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div className="relative mx-auto flex w-full max-w-[1240px] flex-col gap-12 px-5 py-16 sm:px-8 lg:py-20">
        <div className="flex flex-col gap-10 md:flex-row md:items-center md:justify-between">
          <div>
            <BrandMark />
            <p className="mt-4 text-sm text-hero-muted">Supporting people. Stronger workplaces.</p>
          </div>
          {linked ? (
            <nav aria-label="Footer">
              <ul className="flex flex-col gap-2 sm:flex-row sm:gap-8">
                {FOOTER_LINKS.map((link) => (
                  <li key={link.href}>
                    <a
                      className="inline-flex min-h-11 items-center text-sm font-medium text-hero-navy transition-colors duration-200 hover:text-hero-blue"
                      href={link.href}
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}
        </div>
        <div className="border-t border-hero-border pt-8 pb-8">
          <p className="text-sm text-hero-muted">© {new Date().getFullYear()} HeroOS. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
