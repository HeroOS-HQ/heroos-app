import { ClosingIllustration } from "./closing-illustration";
import { ArrowRightIcon } from "./icons";
import { Reveal } from "./reveal";

export function ClosingCta() {
  return (
    <section aria-labelledby="closing-heading" className="px-5 py-24 sm:px-8 sm:py-28 lg:py-36">
      <Reveal className="mx-auto w-full max-w-[1240px]">
        <div className="relative overflow-hidden rounded-[2rem] border border-hero-border bg-gradient-to-br from-white via-[#f8faff] to-hero-yellow-tint px-8 py-14 shadow-hero-card sm:px-14 sm:py-16 lg:px-20 lg:py-20">
          <div className="relative z-10 max-w-xl">
            <h2 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]" id="closing-heading">
              Ready to explore Hero<span className="text-hero-blue">OS</span>?
            </h2>
            <p className="mt-5 text-lg text-hero-muted">Set up your company workspace in a few minutes.</p>
            <a
              className="group mt-10 inline-flex h-14 items-center justify-center gap-2 rounded-full bg-hero-yellow px-8 text-base font-bold text-hero-navy shadow-[0_8px_20px_-8px_rgb(255_212_1/0.9)] transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_24px_-8px_rgb(255_212_1/1)]"
              href="/auth/signup"
            >
              Get started
              <ArrowRightIcon className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </a>
            <p className="mt-5 text-base text-hero-muted">
              Already have an account?{" "}
              <a className="font-bold text-hero-blue-ink underline-offset-4 hover:underline" href="/auth/login">
                Sign in
              </a>
            </p>
          </div>
          {/*
           * Phones and tablets: a strip under the links, bleeding to the card's edges.
           * Desktop: the column beside the text (which ends at 5rem padding + 36rem).
           * Masks fade the scene's cut edge into the card.
           */}
          <div className="pointer-events-none relative -mx-8 -mb-14 mt-4 h-40 [mask-image:linear-gradient(to_bottom,transparent,#000_25%)] sm:-mx-14 sm:-mb-16 sm:mt-8 sm:h-52 lg:absolute lg:inset-y-0 lg:left-[41rem] lg:right-0 lg:m-0 lg:h-auto lg:[mask-image:linear-gradient(to_right,transparent,#000_18%)]">
            <ClosingIllustration className="size-full" />
          </div>
        </div>
      </Reveal>
    </section>
  );
}
