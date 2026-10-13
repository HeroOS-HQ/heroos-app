import { BuildingIcon, CaseIcon, ShieldIcon } from "./icons";
import { Reveal } from "./reveal";

const CAPABILITIES = [
  {
    title: "Secure sign-in",
    body: "Protected access for authorised users.",
    icon: <ShieldIcon className="size-7" />,
  },
  {
    title: "Separate company workspaces",
    body: "Each company's information stays separate.",
    icon: <BuildingIcon className="size-7" />,
  },
  {
    title: "Case visibility",
    body: "See your cases in one clear workspace.",
    icon: <CaseIcon className="size-7" />,
  },
] as const;

/** The three capabilities that exist in the product today. Add nothing that is not built. */
export function PlatformFoundation() {
  return (
    <section
      aria-labelledby="platform-heading"
      className="scroll-mt-20 bg-white/60 px-5 py-24 sm:px-8 sm:py-28 lg:py-36"
      id="platform"
    >
      <div className="mx-auto w-full max-w-[1240px]">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]" id="platform-heading">
            Built on a secure foundation
          </h2>
          <p className="mt-5 text-lg text-hero-muted">What is in place today.</p>
        </Reveal>

        <ul className="mt-12 grid gap-6 lg:mt-14 lg:grid-cols-3 lg:gap-8">
          {CAPABILITIES.map((item, index) => (
            <li key={item.title}>
              <Reveal className="h-full" index={index as 0 | 1 | 2}>
                <div className="flex h-full flex-col rounded-3xl border border-hero-border bg-hero-bg p-8 transition-[transform,box-shadow] duration-200 hover:-translate-y-1 hover:shadow-hero-card-hover lg:p-10">
                  <span className="flex size-14 items-center justify-center rounded-2xl bg-hero-blue-tint text-hero-blue-ink">
                    {item.icon}
                  </span>
                  <h3 className="mt-7 text-xl font-bold leading-snug">{item.title}</h3>
                  <p className="mt-3 text-base leading-relaxed text-hero-muted">{item.body}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
