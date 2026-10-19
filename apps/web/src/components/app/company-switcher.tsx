"use client";

import { useEffect, useId, useRef, useState } from "react";

import { BuildingIcon, CheckIcon, ChevronDownIcon } from "@/components/site/icons";

export type SwitcherItem = { companyId: string; name: string };

/** The current Company's name in the header, with the building symbol; shared by the pill and the switcher. */
export const identityPill =
  "inline-flex min-h-11 min-w-0 max-w-full items-center gap-2.5 rounded-xl border border-hero-border bg-white px-3 text-[0.9375rem] font-bold text-hero-navy shadow-[0_1px_2px_rgb(14_30_61/0.05)] sm:px-3.5";

/**
 * The current Company when the account can open only this one: its name, not
 * a menu (there is nothing to choose).
 */
export function CompanyIdentity({ name }: { name: string }) {
  return (
    <p className={identityPill}>
      <BuildingIcon className="size-5 shrink-0 text-hero-blue" />
      <span className="sr-only">Company: </span>
      <span className="min-w-0 truncate">{name}</span>
    </p>
  );
}

/**
 * Switch between the Companies the API listed for this user (`GET
 * /me/companies`), shown as the current Company's name. Links are
 * deliberately full page loads: every workspace is rendered fresh on the
 * server for the chosen Company, nothing from the previous Company stays in
 * client state or the router cache, and the unsaved-changes warning of the
 * settings form applies. The id in the link is only a resource identifier;
 * the API authorizes the destination.
 */
export function CompanySwitcher({ currentId, items }: { currentId: string; items: SwitcherItem[] }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const current = items.find((item) => item.companyId === currentId);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    // Phones: the panel spans the (sticky, positioned) header below it. Wider
    // screens: it hangs from the button.
    <div className="min-w-0 sm:relative">
      <button
        aria-controls={panelId}
        aria-expanded={open}
        className={`${identityPill} transition-colors duration-150 hover:bg-hero-blue-tint`}
        onClick={() => setOpen((value) => !value)}
        ref={buttonRef}
        type="button"
      >
        {/* The name says which Company is open; the button's name says what it does. */}
        <span className="sr-only">Switch company. Current company: </span>
        <BuildingIcon className="size-5 shrink-0 text-hero-blue" />
        <span className="min-w-0 truncate">{current?.name ?? "Switch company"}</span>
        <ChevronDownIcon className={`size-4 shrink-0 transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div
          className="fade-swap absolute inset-x-4 top-full z-50 mt-2 rounded-2xl border border-hero-border bg-white p-2 shadow-hero-card-hover sm:inset-x-auto sm:left-0 sm:w-80"
          id={panelId}
          ref={panelRef}
        >
          <nav aria-label="Your companies">
            <ul className="flex flex-col">
              {items.map((item) => {
                const selected = item.companyId === currentId;
                return (
                  <li key={item.companyId}>
                    <a
                      aria-current={selected ? "page" : undefined}
                      className="flex min-h-11 items-center justify-between gap-3 rounded-xl px-3 py-2 text-[0.9375rem] font-semibold text-hero-navy hover:bg-hero-blue-tint aria-[current=page]:bg-hero-bg"
                      href={`/workspaces/${encodeURIComponent(item.companyId)}`}
                    >
                      <span className="min-w-0 break-words">{item.name}</span>
                      {selected ? <CheckIcon className="size-4 shrink-0 text-hero-blue" /> : null}
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="mt-1 border-t border-hero-border pt-1">
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full page load per Company (see above) */}
            <a
              className="flex min-h-11 items-center rounded-xl px-3 text-sm font-bold text-hero-blue-ink hover:bg-hero-blue-tint hover:underline"
              href="/workspaces"
            >
              All workspaces
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
