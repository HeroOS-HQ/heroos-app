import { ArrowRightIcon, ClockIcon } from "@/components/site/icons";
import { buttonPrimary } from "@/components/ui/styles";
import { readinessCopy } from "@/lib/onboarding/copy";
import type { Blueprint } from "@/lib/server/heroos-api";

/**
 * What an unconfirmed (or unsupported) Company jurisdiction means for the
 * Disciplinary workflow, from the API's readiness only. Nothing is shown once
 * the API confirmed a supported jurisdiction, or without a Company profile.
 */
export function JurisdictionBanner({
  blueprint,
  companyId,
  variant,
}: {
  blueprint: Blueprint | null;
  companyId: string;
  variant: "overview" | "cases";
}) {
  if (blueprint === null) return null;
  const copy = readinessCopy(blueprint.jurisdiction);
  if (copy.tone === "positive") return null;
  const unsupported = blueprint.jurisdiction.readiness === "unsupported";
  const title = unsupported
    ? copy.title
    : variant === "overview"
      ? "Guided steps need a confirmed jurisdiction first."
      : "Case progression depends on your jurisdiction status.";
  const body = unsupported
    ? copy.body
    : variant === "overview"
      ? "You can create and record cases now. Jurisdiction-specific steps also need approved workflow rules."
      : "You can create and record cases now. Some stages and actions stay restricted until your company's employment jurisdiction is confirmed.";
  return (
    <section
      aria-labelledby="jurisdiction-banner-heading"
      className="flex flex-col gap-4 rounded-[1.25rem] border border-[#f1e2a6] bg-[#fffaea] px-5 py-4 sm:flex-row sm:items-center sm:px-6"
    >
      <span className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-hero-yellow text-hero-navy">
        <ClockIcon className="size-7" />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[1.0625rem] font-extrabold leading-snug text-hero-navy" id="jurisdiction-banner-heading">
          {title}
        </h2>
        <p className="mt-1 max-w-[48rem] text-[0.9375rem] leading-relaxed text-hero-navy/80">{body}</p>
      </div>
      <a
        className={`${buttonPrimary} min-h-12 shrink-0 rounded-xl px-5 text-[0.9375rem]`}
        href={`/workspaces/${encodeURIComponent(companyId)}/settings`}
      >
        View jurisdiction status
        <ArrowRightIcon className="size-4" />
      </a>
    </section>
  );
}
