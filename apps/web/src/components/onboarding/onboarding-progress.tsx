import { CheckIcon } from "@/components/site/icons";

/**
 * The six stages of the founder's setup journey (JJ design review, screens
 * 01–05, plus "About Your Company" for the Blueprint's company context,
 * M2-NEW-03). They are stages of the interface, not of anything saved:
 * Welcome, Company Basics, About Your Company, Jurisdiction and Review are one
 * form held in the browser's memory, and Complete is the ready page, shown
 * only after the API confirmed the registration and read the Company back.
 */
export const STAGES = [
  { key: "welcome", label: "Welcome" },
  { key: "company", label: "Company Basics" },
  { key: "context", label: "About Your Company" },
  { key: "licensing", label: "Jurisdiction" },
  { key: "review", label: "Review" },
  { key: "complete", label: "Complete" },
] as const;

export type StageKey = (typeof STAGES)[number]["key"];

export function stageNumber(stage: StageKey): number {
  return STAGES.findIndex((item) => item.key === stage) + 1;
}

/**
 * Horizontal progress below the header: navy checks for the stages behind,
 * a yellow numbered circle for the current one, outlined circles ahead.
 * Phones show "Step N of 6" with a six-part track instead. Completed stages
 * also say "(completed)" to assistive technology, never colour alone.
 */
export function OnboardingProgress({ current }: { current: StageKey }) {
  const index = stageNumber(current) - 1;
  return (
    <div className="px-4 pb-3 pt-4 sm:px-8 md:pb-3 md:pt-[1.125rem] xl:px-14">
      <p className="text-sm font-bold text-hero-navy md:hidden">
        Step {index + 1} of {STAGES.length}
        <span className="font-semibold text-hero-muted"> · {STAGES[index].label}</span>
      </p>
      <div aria-hidden="true" className="mt-2 grid grid-cols-6 gap-1.5 md:hidden">
        {STAGES.map((stage, position) => (
          <span
            className={`h-1.5 rounded-full ${position < index ? "bg-hero-navy" : position === index ? "bg-hero-yellow" : "bg-[#d9dee7]"}`}
            key={stage.key}
          />
        ))}
      </div>
      <ol aria-label="Setup progress" className="hidden grid-cols-6 md:grid xl:mr-14">
        {STAGES.map((stage, position) => {
          const done = position < index;
          const active = position === index;
          return (
            <li
              aria-current={active ? "step" : undefined}
              className="relative flex flex-col items-center text-center"
              key={stage.key}
            >
              {position < STAGES.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={`absolute left-[calc(50%+1.5rem)] right-[calc(-50%+1.5rem)] top-[1.1875rem] h-0.5 rounded-full ${
                    done ? "bg-hero-navy" : "bg-[#d5dae3]"
                  }`}
                />
              ) : null}
              <span
                className={`relative inline-flex size-10 items-center justify-center rounded-full text-[1.0625rem] font-extrabold ${
                  done
                    ? "bg-hero-navy text-white"
                    : active
                      ? "bg-hero-yellow text-hero-navy shadow-[0_0_0_6px_rgb(255_212_1/0.2)]"
                      : "border-2 border-hero-control bg-white text-hero-muted"
                }`}
              >
                {done ? <CheckIcon className="size-5 stroke-[2.5]" /> : position + 1}
              </span>
              <span
                className={`mt-2.5 px-1 text-sm leading-snug lg:text-base ${
                  active ? "font-bold text-hero-navy" : done ? "font-medium text-hero-navy" : "font-medium text-hero-muted"
                }`}
              >
                {stage.label}
                {done ? <span className="sr-only"> (completed)</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
