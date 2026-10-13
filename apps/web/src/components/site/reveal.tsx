"use client";

import { type ReactNode, useEffect, useRef } from "react";

/**
 * One-time scroll reveal. Content is visible in the server HTML; after mount
 * only elements that start below the fold are hidden, then shown when they
 * scroll into view. No JavaScript, or reduced motion, means no hiding at all
 * (see globals.css). `index` staggers siblings by a small step.
 */
export function Reveal({
  children,
  className,
  index = 0,
}: {
  children: ReactNode;
  className?: string;
  index?: 0 | 1 | 2 | 3;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    if (element.getBoundingClientRect().top < window.innerHeight * 0.92) return;

    element.dataset.reveal = "hidden";
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        element.dataset.reveal = "shown";
        observer.disconnect();
      },
      { threshold: 0.15, rootMargin: "0px 0px -6% 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={className} data-reveal="shown" data-reveal-index={index || undefined}>
      {children}
    </div>
  );
}
