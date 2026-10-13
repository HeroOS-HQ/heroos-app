import { ArrowRightIcon } from "./icons";
import { DemoNotice } from "./demo-notice";
import { HeroIllustration } from "./hero-illustration";

const primaryCta =
  "group inline-flex h-14 items-center justify-center gap-2 rounded-full bg-hero-yellow px-8 text-base font-bold text-hero-navy shadow-[0_8px_20px_-8px_rgb(255_212_1/0.9)] transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_24px_-8px_rgb(255_212_1/1)]";
const secondaryCta =
  "group inline-flex h-14 items-center justify-center gap-2 rounded-full border-2 border-hero-blue bg-transparent px-8 text-base font-bold text-hero-blue transition-[background-color,transform] duration-200 hover:-translate-y-0.5 hover:bg-hero-blue-tint";

export function HeroSection() {
  return (
    <section
      aria-labelledby="hero-heading"
      className="relative scroll-mt-20 overflow-hidden"
      id="top"
    >
      <div className="mx-auto grid w-full max-w-[1240px] items-center gap-10 px-5 pb-20 pt-14 sm:px-8 sm:pt-16 lg:min-h-[700px] lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-6 lg:pb-28 lg:pt-20">
        <div className="max-w-[700px]">
          <p className="enter enter-1 text-xs font-bold uppercase tracking-[0.18em] text-hero-blue-ink sm:text-[13px]">
            Supporting people. Stronger workplaces.
          </p>
          <h1
            className="enter enter-1 mt-6 text-[2.25rem] font-extrabold leading-[1.1] tracking-[-0.03em] text-hero-navy sm:text-[3.25rem] lg:text-[2.6rem] xl:text-[3.1rem]"
            id="hero-heading"
          >
            Your HR Department <span className="sm:block">without an HR Department</span>
          </h1>
          <div className="enter enter-2 mt-8 max-w-[30rem] text-lg leading-relaxed text-hero-muted sm:text-xl">
            <p>No HR expertise required.</p>
            <p>Just describe your situation.</p>
          </div>
          <div className="enter enter-3 mt-10 flex flex-col gap-4 sm:flex-row">
            {/* Plain links, not next/link: the auth routes must not be prefetched. */}
            <a className={primaryCta} href="/auth/signup">
              Get started
              <ArrowRightIcon className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </a>
            <a className={secondaryCta} href="#how-it-works">
              Explore HeroOS
              <ArrowRightIcon className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </a>
          </div>
          <p className="enter enter-3 mt-5 text-base text-hero-muted">
            Already have an account?{" "}
            <a className="font-bold text-hero-blue-ink underline-offset-4 hover:underline" href="/auth/login">
              Sign in
            </a>
          </p>
          <DemoNotice className="enter enter-4 mt-8" />
        </div>

        <div className="enter enter-2 mx-auto w-full max-w-[460px] sm:max-w-[520px] lg:max-w-none">
          <HeroIllustration className="h-auto w-full" />
        </div>
      </div>
    </section>
  );
}
