type Tone = "positive" | "neutral" | "caution" | "muted";

const TONES: Record<Tone, string> = {
  positive: "border-[#b8dcc6] bg-hero-success-tint text-hero-success",
  neutral: "border-[#cfe0f8] bg-hero-blue-tint text-hero-blue-ink",
  caution: "border-[#f1df8d] bg-hero-yellow-tint text-hero-navy",
  muted: "border-hero-border bg-hero-bg text-hero-muted",
};

const DOTS: Record<Tone, string> = {
  positive: "bg-hero-success",
  neutral: "bg-hero-blue",
  caution: "bg-[#b38f00]",
  muted: "bg-hero-muted",
};

/**
 * A short status in words; the colour only reinforces it. `wrap` lets a long
 * status (an API label) wrap in a narrow column instead of widening it.
 */
export function StatusBadge({ tone, children, wrap = false }: { tone: Tone; children: string; wrap?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-2.5 py-0.5 text-[0.8125rem] font-bold ${
        wrap ? "max-w-full rounded-xl leading-snug" : "whitespace-nowrap rounded-full"
      } ${TONES[tone]}`}
    >
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${DOTS[tone]}`} />
      {children}
    </span>
  );
}
