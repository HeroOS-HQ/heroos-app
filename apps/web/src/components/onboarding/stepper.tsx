import { CheckIcon } from "@/components/site/icons";

export const STEPS = [
  { key: "company", label: "Company details" },
  { key: "licensing", label: "Licensing" },
  { key: "review", label: "Review" },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

/**
 * Three-step progress. Wider screens show the labelled steps; narrow screens
 * show "Step N of 3" and a three-segment track. Completed steps are marked
 * with a check *and* the words "completed" for assistive technology.
 */
export function Stepper({ current }: { current: StepKey }) {
  const index = STEPS.findIndex((step) => step.key === current);
  return (
    <div className="mx-auto mb-6 w-full max-w-[52rem] sm:mb-8">
      <p className="text-sm font-bold text-hero-navy sm:hidden">
        Step {index + 1} of {STEPS.length}
        <span className="font-semibold text-hero-muted"> · {STEPS[index].label}</span>
      </p>
      <div aria-hidden="true" className="mt-2 grid grid-cols-3 gap-1.5 sm:hidden">
        {STEPS.map((step, position) => (
          <span
            className={`h-1.5 rounded-full ${position <= index ? "bg-hero-yellow" : "bg-[#e1e4ea]"}`}
            key={step.key}
          />
        ))}
      </div>
      <ol aria-label="Setup progress" className="hidden items-center gap-3 sm:flex">
        {STEPS.map((step, position) => {
          const done = position < index;
          const active = position === index;
          return (
            <li
              aria-current={active ? "step" : undefined}
              className="flex flex-1 items-center gap-3 text-sm font-bold text-hero-muted aria-[current=step]:text-hero-navy"
              key={step.key}
            >
              <span
                className={`inline-flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-extrabold ${
                  done || active
                    ? "border-hero-yellow bg-hero-yellow text-hero-navy"
                    : "border-hero-control bg-white text-hero-muted"
                }`}
              >
                {done ? <CheckIcon className="size-4" /> : position + 1}
              </span>
              <span>
                {step.label}
                {done ? <span className="sr-only"> (completed)</span> : null}
              </span>
              {position < STEPS.length - 1 ? (
                <span aria-hidden="true" className={`h-0.5 flex-1 rounded-full ${done ? "bg-hero-yellow" : "bg-[#e1e4ea]"}`} />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
