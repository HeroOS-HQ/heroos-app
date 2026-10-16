import { ArrowRightIcon, ChecklistIcon, ClockIcon, PeopleIcon, ShieldIcon } from "@/components/site/icons";
import { StatusBadge } from "@/components/ui/status-badge";
import { card, sectionTitle } from "@/components/ui/styles";

const AREAS = [
  {
    key: "disciplinary",
    title: "Disciplinary",
    description: "Guided steps for handling conduct and performance concerns fairly and consistently.",
    Icon: ShieldIcon,
  },
  {
    key: "probation",
    title: "Probation",
    description: "Support for reviewing a new hire's probation period and recording the outcome.",
    Icon: ClockIcon,
  },
  {
    key: "recruitment",
    title: "Recruitment",
    description: "A structured path from defining a role to making an offer.",
    Icon: PeopleIcon,
  },
] as const;

/**
 * The three V1 HR workflows. Disciplinary opens its Cases for Company
 * administrators (M2-02: intake and safety screening, stated on the card); for other
 * members it is shown as administrator-only, with no link. The others are
 * honestly not available yet: no links, no buttons, nothing that suggests a
 * working feature. The API enforces access whatever this shows.
 */
export function WorkflowAreas({ companyId, isAdmin }: { companyId: string; isAdmin: boolean }) {
  return (
    <section aria-labelledby="workflows-heading" className={`${card} p-5 sm:p-8`}>
      <div className="flex items-start gap-3">
        <ChecklistIcon className="mt-0.5 size-6 shrink-0 text-hero-blue" />
        <div>
          <h2 className={sectionTitle} id="workflows-heading">
            HR workflows
          </h2>
          <p className="mt-1 text-[0.9375rem] leading-relaxed text-hero-muted">
            Guided workflows are being built step by step. Disciplinary has its intake; the others will appear here
            when they&apos;re ready.
          </p>
        </div>
      </div>
      <ul className="mt-6 grid gap-4 md:grid-cols-3">
        {AREAS.map(({ key, title, description, Icon }) =>
          key === "disciplinary" && isAdmin ? (
            <li className="flex" key={key}>
              <a
                className="group flex w-full flex-col rounded-2xl border border-hero-blue/30 bg-hero-blue-tint/50 p-5 transition-colors duration-150 hover:bg-hero-blue-tint focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-hero-blue"
                href={`/workspaces/${encodeURIComponent(companyId)}/cases`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex size-10 items-center justify-center rounded-xl bg-white text-hero-blue">
                    <Icon className="size-5" />
                  </span>
                  <StatusBadge tone="neutral">Intake only</StatusBadge>
                </div>
                <h3 className="mt-4 text-base font-extrabold text-hero-navy">{title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-hero-muted">{description}</p>
                <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-bold text-hero-blue-ink">
                  Open Disciplinary cases
                  <ArrowRightIcon className="size-4 transition-transform duration-150 group-hover:translate-x-0.5" />
                </span>
              </a>
            </li>
          ) : (
            <li className="flex flex-col rounded-2xl border border-hero-border bg-hero-bg/60 p-5" key={key}>
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex size-10 items-center justify-center rounded-xl bg-white text-hero-blue">
                  <Icon className="size-5" />
                </span>
                <StatusBadge tone="muted">{key === "disciplinary" ? "Administrators only" : "Coming soon"}</StatusBadge>
              </div>
              <h3 className="mt-4 text-base font-extrabold text-hero-navy">{title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-hero-muted">{description}</p>
            </li>
          ),
        )}
      </ul>
    </section>
  );
}
