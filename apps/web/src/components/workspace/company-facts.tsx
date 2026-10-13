import { licensingLabel } from "@/lib/onboarding/copy";
import type { Blueprint } from "@/lib/server/heroos-api";

/** The saved Company profile as read-only facts (customer statements, unverified). */
export function CompanyFacts({ blueprint }: { blueprint: Blueprint }) {
  const rows: [string, string | null][] = [
    ["Legal business name", blueprint.legalName],
    ["Industry", blueprint.industry],
    ["Number of employees", blueprint.employeeCount === null ? null : blueprint.employeeCount.toLocaleString("en-US")],
    ["Licensed in", blueprint.licensing.location === null ? null : licensingLabel(blueprint.licensing.location)],
  ];
  if (blueprint.licensing.location === "other") rows.push(["Licensing authority", blueprint.licensing.authority]);
  return (
    <dl className="divide-y divide-hero-border">
      {rows.map(([label, value]) => (
        <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6" key={label}>
          <dt className="text-sm text-hero-muted">{label}</dt>
          <dd className="min-w-0 break-words text-[0.9375rem] font-semibold text-hero-navy sm:max-w-[60%] sm:text-right">
            {value ?? <span className="font-normal text-hero-muted">Not provided</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
