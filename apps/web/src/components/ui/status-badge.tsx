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

/** A short status in words; the colour only reinforces it. */
export function StatusBadge({ tone, children }: { tone: Tone; children: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[0.8125rem] font-bold ${TONES[tone]}`}
    >
      <span aria-hidden="true" className={`size-1.5 rounded-full ${DOTS[tone]}`} />
      {children}
    </span>
  );
}
