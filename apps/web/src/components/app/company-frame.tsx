"use client";

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/site/brand-mark";
import { DemoNotice } from "@/components/site/demo-notice";
import {
  BuildingIcon,
  CaseIcon,
  CloseIcon,
  DocumentIcon,
  HomeIcon,
  LockIcon,
  MenuIcon,
  PeopleIcon,
} from "@/components/site/icons";

import { SignOutButton } from "./app-shell";
import { BackForwardCacheGuard } from "./back-forward-cache-guard";
import { CompanyIdentity, CompanySwitcher, type SwitcherItem } from "./company-switcher";

/** The company navigation's sections; each is one real route. */
export type CompanySection = "dashboard" | "blueprint" | "services" | "cases";

type NavItem = {
  key: CompanySection | "team";
  label: string;
  icon: ReactNode;
  /** null: shown, but not available (no link, nothing to click). */
  href: string | null;
  unavailable?: string;
};

export type CompanyFrameProps = {
  companyId: string;
  companyName: string;
  /** Every Company the API listed for this account; a switcher only when there is more than one. */
  companies: SwitcherItem[];
  /** The account's role here, in words (from the API's membership answer). */
  role: string | null;
  /** Company administrator (the API's answer; it enforces access whatever this shows). */
  admin: boolean;
  /** The section the page belongs to (highlighted in the navigation). */
  current?: CompanySection;
  /**
   * standard: the company navigation beside the page. case: the Case
   * workspace brings its own case list instead (never two sidebars).
   */
  mode?: "standard" | "case";
  children: ReactNode;
};

/** With its 1px border the header is 74px tall on large screens (the pages below are offset by that). */
export const HEADER_HEIGHT = "h-16 lg:h-[73px]";

/**
 * The signed-in frame of one Company's workspace (JJ design review, screens
 * 06–10): a full-width header with the Company's identity, and on standard
 * pages a persistent navigation of the Company's real routes. Sections that
 * don't exist yet are listed as such, never as links. On smaller screens the
 * navigation opens as a panel from the header.
 */
export function CompanyFrame({
  companyId,
  companyName,
  companies,
  role,
  admin,
  current,
  mode = "standard",
  children,
}: CompanyFrameProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLButtonElement>(null);
  const base = `/workspaces/${encodeURIComponent(companyId)}`;
  const standard = mode === "standard";

  const items: NavItem[] = [
    { key: "dashboard", label: "Dashboard", icon: <HomeIcon className="size-[1.375rem]" />, href: base },
    {
      key: "blueprint",
      label: "Company Blueprint",
      icon: <BuildingIcon className="size-[1.375rem]" />,
      href: `${base}/settings`,
    },
    { key: "services", label: "HR Services", icon: <CaseIcon className="size-[1.375rem]" />, href: `${base}/hr-services` },
    {
      key: "cases",
      label: "Cases",
      icon: <DocumentIcon className="size-[1.375rem]" />,
      // Disciplinary Cases are for administrators (M2-01); the API refuses everyone else.
      href: admin ? `${base}/cases` : null,
      unavailable: admin ? undefined : "Administrators only",
    },
    {
      key: "team",
      label: "Team & Access",
      icon: <PeopleIcon className="size-[1.375rem]" />,
      href: null,
      unavailable: "Coming soon",
    },
  ];

  const close = useCallback(() => {
    setOpen(false);
    requestAnimationFrame(() => menuRef.current?.focus());
  }, []);

  // The navigation panel (smaller screens): Escape closes it, focus moves in and back.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => document.getElementById("company-nav-close")?.focus());
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  return (
    <>
      <BackForwardCacheGuard />
      <a
        className="sr-only z-[60] rounded-full bg-hero-yellow px-5 py-3 font-bold text-hero-navy focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
        href="#main"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-hero-border bg-white">
        <div className={`flex items-center gap-2 px-3 sm:gap-3 sm:px-5 lg:px-6 ${HEADER_HEIGHT}`}>
          {/* At lg the logo column matches the navigation, so the Company sits above the page. */}
          <div className="flex shrink-0 items-center lg:w-[13.375rem]">
            <a
              aria-label="HeroOS: company dashboard"
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg"
              href={base}
            >
              <BrandMark compact />
            </a>
          </div>
          <div className="flex min-w-0 flex-1 items-center">
            {companies.length > 1 ? (
              <CompanySwitcher currentId={companyId} items={companies} />
            ) : (
              <CompanyIdentity name={companyName} />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            {role ? (
              <p className="hidden items-center gap-2 text-sm font-semibold text-hero-muted md:inline-flex">
                <span className="sr-only">Your role: </span>
                {role}
              </p>
            ) : null}
            <SignOutButton />
            {standard ? (
              <button
                aria-controls="company-nav"
                aria-expanded={open}
                aria-label="Menu"
                className="inline-flex size-11 items-center justify-center rounded-full text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint lg:hidden"
                onClick={() => setOpen(true)}
                ref={menuRef}
                type="button"
              >
                <MenuIcon className="size-6" />
              </button>
            ) : null}
          </div>
        </div>
      </header>

      {standard ? (
        <div className="flex flex-1 flex-col lg:grid lg:grid-cols-[14.625rem_minmax(0,1fr)]">
          {open ? (
            <div aria-hidden="true" className="fixed inset-0 z-[45] bg-hero-navy/35 lg:hidden" onClick={close} />
          ) : null}
          <aside
            aria-label="Company navigation"
            className={`${
              open ? "fixed inset-y-0 left-0 z-50 flex w-[min(18rem,86vw)] shadow-2xl" : "hidden"
            } flex-col overflow-y-auto border-r border-hero-border bg-white lg:sticky lg:top-[74px] lg:z-auto lg:flex lg:h-[calc(100dvh-74px)] lg:w-auto lg:self-start lg:shadow-none`}
            id="company-nav"
          >
            <div className="flex items-center justify-between px-4 pt-3 lg:hidden">
              <p className="text-sm font-extrabold text-hero-navy">Menu</p>
              <button
                aria-label="Close the menu"
                className="inline-flex size-11 items-center justify-center rounded-full text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint"
                id="company-nav-close"
                onClick={close}
                type="button"
              >
                <CloseIcon className="size-5" />
              </button>
            </div>
            <nav aria-label="Company" className="px-3 py-4 lg:py-7">
              <ul className="flex flex-col gap-1.5">
                {items.map((item) => (
                  <li key={item.key}>
                    {item.href ? (
                      <a
                        aria-current={item.key === current ? "page" : undefined}
                        className="flex min-h-12 items-center gap-3 rounded-xl px-3 text-base font-semibold text-hero-navy transition-colors duration-150 hover:bg-hero-bg aria-[current=page]:bg-hero-yellow-tint aria-[current=page]:font-bold aria-[current=page]:shadow-[inset_0_0_0_1px_rgb(241_223_141/0.9)]"
                        href={item.href}
                      >
                        {item.icon}
                        <span className="min-w-0 flex-1">{item.label}</span>
                      </a>
                    ) : (
                      // Not a link and not focusable: there is nothing to open yet.
                      <p className="flex min-h-12 items-center gap-3 rounded-xl px-3 text-base font-semibold text-hero-muted">
                        {item.icon}
                        <span className="min-w-0 flex-1">
                          {item.label}
                          <span className="block text-xs font-semibold text-hero-muted">{item.unavailable}</span>
                        </span>
                        <LockIcon className="size-4 shrink-0" />
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            {/* scroll-mt: in-page links and the skip link scroll here; keep it clear of the sticky header. */}
            <main className="flex-1 scroll-mt-20" id="main" tabIndex={-1}>
              {children}
            </main>
            <footer className="border-t border-hero-border bg-white">
              <div className="flex flex-col gap-1 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
                <DemoNotice />
                <p className="text-sm text-hero-muted">© HeroOS</p>
              </div>
            </footer>
          </div>
        </div>
      ) : (
        <>
          <main className="flex min-w-0 flex-1 flex-col scroll-mt-20" id="main" tabIndex={-1}>
            {children}
          </main>
          {/* The case list carries the environment notice on large screens; the page footer does elsewhere. */}
          <footer className="border-t border-hero-border bg-white lg:hidden">
            <div className="flex flex-col gap-1 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <DemoNotice />
              <p className="text-sm text-hero-muted">© HeroOS</p>
            </div>
          </footer>
        </>
      )}
    </>
  );
}
