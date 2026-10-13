import { StatusBadge } from "@/components/ui/status-badge";
import { readinessCopy } from "@/lib/onboarding/copy";
import type { Blueprint } from "@/lib/server/heroos-api";

/**
 * Jurisdiction readiness exactly as the HeroOS API reports it. The licensing
 * answer is shown elsewhere and never turned into a jurisdiction here: only
 * a backend confirmation (`supported_confirmed` / `unsupported`) names one.
 */
export function JurisdictionStatus({
  jurisdiction,
  headingLevel = 3,
}: {
  jurisdiction: Blueprint["jurisdiction"];
  headingLevel?: 2 | 3;
}) {
  const copy = readinessCopy(jurisdiction);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <div
      className={`rounded-2xl border px-4 py-4 sm:px-5 ${
        copy.tone === "positive"
          ? "border-[#b8dcc6] bg-hero-success-tint"
          : copy.tone === "caution"
            ? "border-[#f1df8d] bg-hero-yellow-tint"
            : "border-[#cfe0f8] bg-hero-blue-tint"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading className="text-base font-extrabold text-hero-navy">{copy.title}</Heading>
        <StatusBadge tone={copy.tone === "positive" ? "positive" : copy.tone === "caution" ? "caution" : "neutral"}>
          {copy.status}
        </StatusBadge>
      </div>
      <p className="mt-2 text-[0.9375rem] leading-relaxed text-hero-navy/85">{copy.body}</p>
    </div>
  );
}
