import type { ReactNode } from "react";

type Tone = "info" | "caution" | "danger" | "success";

const TONES: Record<Tone, string> = {
  info: "border-[#cfe0f8] bg-hero-blue-tint",
  caution: "border-[#f1df8d] bg-hero-yellow-tint",
  danger: "border-[#e9b4c0] bg-hero-danger-tint",
  success: "border-[#b8dcc6] bg-hero-success-tint",
};

/**
 * A bordered message box. The tone is decoration only: the title and text
 * always say what the state is. `role` makes it a live region when the
 * content appears in response to an action.
 */
export function Notice({
  tone = "info",
  title,
  children,
  role,
  className,
  id,
  tabIndex,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  role?: "status" | "alert";
  className?: string;
  id?: string;
  tabIndex?: number;
}) {
  return (
    <div
      className={`rounded-2xl border px-4 py-3.5 text-hero-navy sm:px-5 sm:py-4 ${TONES[tone]} ${className ?? ""}`}
      id={id}
      role={role}
      tabIndex={tabIndex}
    >
      {title ? <p className="font-bold">{title}</p> : null}
      {children ? <div className={`text-[0.9375rem] leading-relaxed text-hero-navy/85 ${title ? "mt-1" : ""}`}>{children}</div> : null}
    </div>
  );
}
