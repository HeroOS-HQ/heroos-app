"use client";

import { useEffect, useId, useRef, useState } from "react";

import { BuildingIcon, ChevronDownIcon, StoreIcon } from "@/components/site/icons";

import { PersonAvatar } from "./workspace-chrome";

export type MenuPage = "blueprint" | "space";

/**
 * The account menu (approved design): the only way to the Company Blueprint
 * and Company Space, never permanent navigation. Utilities below: another
 * workspace (when the account has several) and sign out. Everything it names
 * is the API's answer for this account; there is no account-settings page yet,
 * so none is offered.
 */
export function AccountMenu({
  companyId,
  companyName,
  roleLabel,
  multipleWorkspaces,
  current,
}: {
  companyId: string;
  companyName: string;
  roleLabel: string | null;
  multipleWorkspaces: boolean;
  current?: MenuPage;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  const base = `/workspaces/${encodeURIComponent(companyId)}`;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const pages = [
    {
      key: "blueprint" as const,
      label: "Company Blueprint",
      note: "Company details and jurisdiction",
      icon: <BuildingIcon className="size-5" />,
      href: `${base}/settings`,
    },
    {
      key: "space" as const,
      label: "Company Space",
      note: "Your access and company overview",
      icon: <StoreIcon className="size-5" />,
      href: `${base}/space`,
    },
  ];
  const utility =
    "flex min-h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-[0.875rem] font-semibold text-hero-navy/80 transition-colors duration-150 hover:bg-hero-navy/[0.04] hover:text-hero-navy";

  return (
    <div className="relative" ref={root}>
      <button
        aria-controls={id}
        aria-expanded={open}
        aria-label={`Account menu: ${companyName}`}
        className="inline-flex min-h-11 items-center gap-1 rounded-full p-1 transition-colors duration-150 hover:bg-hero-navy/[0.05] aria-expanded:bg-white aria-expanded:shadow-[0_0_0_1px_rgb(14_30_61/0.1)] sm:pr-2"
        onClick={() => setOpen((value) => !value)}
        ref={button}
        type="button"
      >
        <PersonAvatar className="size-9" />
        <ChevronDownIcon className="size-4 text-hero-muted max-sm:hidden" />
      </button>
      <div
        className="ws-rise absolute right-0 top-full z-30 mt-2 w-[min(19rem,calc(100vw-1rem))] rounded-2xl border border-hero-border bg-white p-2 text-left shadow-[0_24px_48px_-20px_rgb(14_30_61/0.45)]"
        hidden={!open}
        id={id}
      >
        <div className="flex items-center gap-3 px-3 py-2.5">
          <PersonAvatar className="size-10" />
          <div className="min-w-0">
            <p className="truncate font-bold text-hero-navy">{companyName}</p>
            {roleLabel ? <p className="truncate text-[0.8125rem] text-hero-muted">{roleLabel}</p> : null}
          </div>
        </div>
        <div className="my-1 h-px bg-hero-border" />
        <ul aria-label="Company">
          {pages.map((page) => (
            <li key={page.key}>
              <a
                aria-current={page.key === current ? "page" : undefined}
                className="flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors duration-150 hover:bg-hero-navy/[0.04] aria-[current=page]:bg-hero-blue-tint/70"
                href={page.href}
              >
                <span className="mt-0.5 text-hero-muted">{page.icon}</span>
                <span className="min-w-0">
                  <span className="block text-[0.9375rem] font-semibold text-hero-navy">{page.label}</span>
                  <span className="block text-[0.8125rem] text-hero-muted">{page.note}</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
        <div className="my-1 h-px bg-hero-border" />
        <ul aria-label="Account">
          {multipleWorkspaces ? (
            <li>
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load: the chooser re-reads the account's workspaces */}
              <a className={utility} href="/workspaces">
                <span aria-hidden="true" className="size-4" />
                Switch workspace
              </a>
            </li>
          ) : null}
          <li>
            <form action="/auth/logout" method="post">
              <button className={utility} type="submit">
                <span aria-hidden="true" className="size-4" />
                Sign out
              </button>
            </form>
          </li>
        </ul>
      </div>
    </div>
  );
}
