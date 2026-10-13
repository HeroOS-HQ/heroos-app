"use client";

import { useEffect, useRef, useState } from "react";

import { BrandMark } from "./brand-mark";
import { CloseIcon, MenuIcon } from "./icons";

const NAV_ITEMS = [
  { id: "top", label: "Home", href: "#top" },
  { id: "how-it-works", label: "Explore HeroOS", href: "#how-it-works" },
  { id: "platform", label: "Platform", href: "#platform" },
] as const;

const getStartedClass =
  "inline-flex h-11 items-center justify-center rounded-full bg-hero-yellow px-5 text-sm font-bold text-hero-navy transition-[background-color,box-shadow,transform] duration-200 hover:-translate-y-px hover:shadow-md focus-visible:-translate-y-px sm:px-6";
const signInClass =
  "hidden h-11 items-center justify-center rounded-full px-4 text-sm font-bold text-hero-navy transition-colors duration-200 hover:bg-hero-blue-tint sm:inline-flex";

/**
 * Landing: wordmark, in-page navigation, Sign in and Get started (hosted
 * sign-up, then company onboarding). Workspace: wordmark only (the workspace
 * has its own sign-out control). Navigation targets are sections of the landing
 * page itself; there is no Pricing or Contact page to link to yet.
 */
export function SiteHeader({ variant }: { variant: "landing" | "workspace" }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [active, setActive] = useState<string>("top");
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (variant !== "landing" || typeof IntersectionObserver === "undefined") return;
    const sections = NAV_ITEMS.map((item) => document.getElementById(item.id)).filter(
      (element): element is HTMLElement => element !== null,
    );
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting);
        if (visible.length > 0) setActive(visible[visible.length - 1].target.id);
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, [variant]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      toggleRef.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <header className="sticky top-0 z-40 border-b border-hero-border bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-[72px] w-full max-w-[1240px] items-center justify-between gap-4 px-5 sm:px-8 lg:h-20">
        <a aria-label="HeroOS home" className="rounded-lg" href={variant === "landing" ? "#top" : "/"}>
          <BrandMark />
        </a>

        {variant === "landing" ? (
          <>
            <nav aria-label="Main" className="hidden md:block">
              <ul className="flex items-center gap-10">
                {NAV_ITEMS.map((item) => (
                  <li key={item.id}>
                    <a
                      aria-current={active === item.id ? "location" : undefined}
                      className="relative inline-block py-2 text-sm font-medium text-hero-navy transition-colors duration-200 hover:text-hero-blue after:absolute after:inset-x-0 after:-bottom-0.5 after:h-0.5 after:origin-left after:scale-x-0 after:rounded-full after:bg-hero-yellow after:transition-transform after:duration-200 hover:after:scale-x-100 aria-[current=location]:after:scale-x-100"
                      href={item.href}
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="flex items-center gap-1 sm:gap-2">
              {/* Plain links, not next/link: the auth routes must not be prefetched. */}
              <a className={signInClass} href="/auth/login">
                Sign in
              </a>
              <a className={getStartedClass} href="/auth/signup">
                Get started
              </a>
              <button
                ref={toggleRef}
                aria-controls="mobile-menu"
                aria-expanded={menuOpen}
                aria-label={menuOpen ? "Close menu" : "Open menu"}
                className="inline-flex size-11 items-center justify-center rounded-full text-hero-navy transition-colors duration-200 hover:bg-hero-blue-tint md:hidden"
                onClick={() => setMenuOpen((open) => !open)}
                type="button"
              >
                {menuOpen ? <CloseIcon /> : <MenuIcon />}
              </button>
            </div>
          </>
        ) : null}
      </div>

      {variant === "landing" && menuOpen ? (
        <nav
          aria-label="Mobile"
          className="fade-swap border-t border-hero-border bg-white px-5 pb-6 pt-2 sm:px-8 md:hidden"
          id="mobile-menu"
        >
          <ul className="flex flex-col">
            {NAV_ITEMS.map((item) => (
              <li key={item.id}>
                <a
                  aria-current={active === item.id ? "location" : undefined}
                  className="flex min-h-12 items-center border-b border-hero-border text-base font-medium text-hero-navy aria-[current=location]:font-bold"
                  href={item.href}
                  onClick={() => setMenuOpen(false)}
                >
                  {item.label}
                </a>
              </li>
            ))}
            <li>
              <a
                className="flex min-h-12 items-center border-b border-hero-border text-base font-bold text-hero-blue-ink"
                href="/auth/login"
              >
                Sign in
              </a>
            </li>
          </ul>
        </nav>
      ) : null}
    </header>
  );
}
