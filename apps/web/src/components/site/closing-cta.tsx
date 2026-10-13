import { ArrowRightIcon } from "./icons";
import { Reveal } from "./reveal";

export function ClosingCta() {
  return (
    <section aria-labelledby="closing-heading" className="px-5 py-24 sm:px-8 sm:py-28 lg:py-36">
      <Reveal className="mx-auto w-full max-w-[1240px]">
        <div className="relative overflow-hidden rounded-[2rem] border border-hero-border bg-gradient-to-br from-hero-blue-tint via-[#f3f7fe] to-hero-yellow-tint px-8 py-14 sm:px-14 sm:py-16 lg:px-20 lg:py-20">
          <div className="relative z-10 max-w-xl">
            <h2 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]" id="closing-heading">
              Ready to explore Hero<span className="text-hero-blue">OS</span>?
            </h2>
            <p className="mt-5 text-lg text-hero-muted">Sign in to see the platform in action.</p>
            <a
              className="group mt-10 inline-flex h-14 items-center justify-center gap-2 rounded-full bg-hero-yellow px-8 text-base font-bold text-hero-navy shadow-[0_8px_20px_-8px_rgb(255_212_1/0.9)] transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_24px_-8px_rgb(255_212_1/1)]"
              href="/auth/login"
            >
              Sign in to HeroOS
              <ArrowRightIcon className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </a>
          </div>
          <svg
            aria-hidden="true"
            className="pointer-events-none absolute -right-10 top-1/2 hidden h-[130%] w-auto -translate-y-1/2 text-hero-light-blue xl:block"
            fill="none"
            viewBox="0 0 400 400"
          >
            <circle cx="200" cy="200" fill="currentColor" fillOpacity="0.1" r="190" />
            <circle cx="200" cy="200" fill="currentColor" fillOpacity="0.1" r="130" />
            <circle cx="150" cy="150" fill="#ffd401" r="26" />
            <path d="M40 300C130 270 200 330 260 280S360 230 400 240" stroke="currentColor" strokeLinecap="round" strokeOpacity="0.6" strokeWidth="3" />
          </svg>
        </div>
      </Reveal>
    </section>
  );
}
