import type { Metadata } from "next";
import { notFound } from "next/navigation";

import "./review.css";

export const metadata: Metadata = {
  title: "Ask HeroOS · Page 1 design review",
  robots: { index: false, follow: false },
};

/**
 * Page 1 design review (20 Oct 2026): static mockups only, no data, no API.
 * Off unless the server is started with HEROOS_DESIGN_REVIEW=1, so it can
 * never appear in a deployment by accident.
 */
export default function DesignReviewLayout({ children }: LayoutProps<"/design-review/oct20">) {
  if (process.env.HEROOS_DESIGN_REVIEW !== "1") notFound();
  return children;
}
