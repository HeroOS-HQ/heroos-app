import type { ReactNode } from "react";

import { AdviserMark } from "@/components/app/workspace-chrome";
import { AlertIcon, LightbulbIcon, PeopleIcon } from "@/components/site/icons";

/**
 * How HeroOS's turns look, by outcome (approved Oct 20 design, Page 1). The
 * outcome is never decided here: today it comes from the deterministic
 * workflow's messages (components/cases/conversation.tsx); M2-NEW-06 passes
 * the outcome the Conditions engine decided for an AI turn into the same
 * component. Every outcome is shown with words and an icon, never colour alone.
 */
export type Outcome = "guidance" | "warning" | "block" | "expert";

/** A stop sign drawn with CSS (no new icon file): an octagon with a bar. */
function StopGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center bg-current [clip-path:polygon(29%_0,71%_0,100%_29%,100%_71%,71%_100%,29%_100%,0_71%,0_29%)] ${className ?? "size-4"}`}
    >
      <span className="h-[2px] w-[55%] rounded bg-white" />
    </span>
  );
}

export const OUTCOME: Record<Outcome, { label: string; tone: string; icon: (className: string) => ReactNode }> = {
  guidance: { label: "Guidance", tone: "tone-guidance", icon: (c) => <LightbulbIcon className={c} /> },
  warning: { label: "Warning", tone: "tone-warning", icon: (c) => <AlertIcon className={c} /> },
  block: { label: "Stop", tone: "tone-stop", icon: (c) => <StopGlyph className={c} /> },
  expert: { label: "Expert Review", tone: "tone-expert", icon: (c) => <PeopleIcon className={c} /> },
};

/**
 * The outcome's label beside "HeroOS". A block shows its stop sign only (JJ,
 * 21 Oct: no "Stop · HeroOS can't proceed" label; the red panel says enough);
 * its name stays for screen readers.
 */
export function OutcomeLabel({ outcome }: { outcome: Outcome }) {
  const { label, tone, icon } = OUTCOME[outcome];
  if (outcome === "block") {
    return (
      <span className={`${tone} inline-flex size-6 items-center justify-center rounded-full bg-(--tone-chip) text-(--tone-ink)`}>
        {icon("size-3.5")}
        <span className="sr-only">{label}</span>
      </span>
    );
  }
  return (
    <span
      className={`${tone} inline-flex h-6 items-center gap-1.5 rounded-full bg-(--tone-chip) px-2.5 text-[0.75rem] font-bold tracking-[0.01em] text-(--tone-ink)`}
    >
      {icon("size-3.5")}
      {label}
    </span>
  );
}

/** A box heading inside a turn ("Next steps", "Still needed", "HeroOS needs to know"). */
export const boxHeading = "text-[0.75rem] font-bold uppercase tracking-[0.1em] text-(--tone-ink)";

/**
 * One HeroOS turn: the mark, "HeroOS", the outcome, and the content.
 * Guidance is text beside a blue rule; a warning, a block and Expert Review
 * are panels with a coloured rail.
 */
export function AdviserTurn({
  id,
  outcome,
  title,
  time,
  children,
}: {
  id: string;
  outcome: Outcome;
  /** The panel's headline (warning, block, Expert Review). */
  title?: ReactNode;
  time?: ReactNode;
  children: ReactNode;
}) {
  const headingId = `turn-${id}`;
  const guidance = outcome === "guidance";
  return (
    <article aria-labelledby={headingId} className={OUTCOME[outcome].tone}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <AdviserMark />
        <h3 className="text-[0.875rem] font-extrabold text-hero-navy" id={headingId}>
          HeroOS<span className="sr-only">, {OUTCOME[outcome].label}</span>
        </h3>
        <OutcomeLabel outcome={outcome} />
        {time ? <span className="ml-auto text-xs tabular-nums text-hero-muted">{time}</span> : null}
      </div>
      <div
        className={
          guidance
            ? "mt-2 space-y-3 border-l-2 border-(--tone-rule) pl-4 text-base leading-[1.65] text-hero-navy sm:ml-[0.9375rem] sm:pl-[1.6875rem]"
            : "relative mt-2.5 space-y-3 overflow-hidden rounded-2xl border border-(--tone-line) bg-(--tone-bg) py-4 pl-5 pr-4 text-base leading-[1.65] text-hero-navy shadow-[0_14px_34px_-26px_rgb(14_30_61/0.5)] sm:ml-11 sm:py-5 sm:pr-5"
        }
      >
        {guidance ? null : <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-(--tone-rail)" />}
        {title ? <p className="text-[1.1875rem] font-extrabold leading-snug tracking-[-0.01em] text-(--tone-ink)">{title}</p> : null}
        {children}
      </div>
    </article>
  );
}
