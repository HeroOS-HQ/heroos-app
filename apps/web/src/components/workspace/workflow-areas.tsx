import { ChecklistIcon, ClockIcon, PeopleIcon, ShieldIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { card, sectionTitle } from "@/components/ui/styles";

const AREAS = [
  {
    title: "Disciplinary",
    description: "Guided steps for handling conduct and performance concerns fairly and consistently.",
    Icon: ShieldIcon,
  },
  {
    title: "Probation",
    description: "Support for reviewing a new hire's probation period and recording the outcome.",
    Icon: ClockIcon,
  },
  {
    title: "Recruitment",
    description: "A structured path from defining a role to making an offer.",
    Icon: PeopleIcon,
  },
] as const;

/**
 * The three V1 HR workflows, shown honestly as not yet available: no links,
 * no buttons, nothing that suggests a working feature.
 */
export function WorkflowAreas() {
  return (
    <section aria-labelledby="workflows-heading" className={`${card} p-5 sm:p-8`}>
      <div className="flex items-start gap-3">
        <ChecklistIcon className="mt-0.5 size-6 shrink-0 text-hero-blue" />
        <div>
          <h2 className={sectionTitle} id="workflows-heading">
            HR workflows
          </h2>
          <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
            These guided workflows are being built. They&apos;ll appear here when they&apos;re ready.
          </p>
        </div>
      </div>
      <ul className="mt-6 grid gap-4 md:grid-cols-3">
        {AREAS.map(({ title, description, Icon }) => (
          <li className="flex flex-col rounded-2xl border border-hero-border bg-hero-bg/60 p-5" key={title}>
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex size-10 items-center justify-center rounded-xl bg-white text-hero-blue">
                <Icon className="size-5" />
              </span>
              <StatusBadge tone="muted">Coming soon</StatusBadge>
            </div>
            <h3 className="mt-4 text-base font-extrabold text-hero-navy">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-hero-muted">{description}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
