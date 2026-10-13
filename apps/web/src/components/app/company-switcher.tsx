"use client";

import { useEffect, useId, useRef, useState } from "react";

import { CheckIcon, ChevronDownIcon } from "@/components/site/icons";

export type SwitcherItem = { companyId: string; name: string };

/**
 * Switch between the Companies the API listed for this user (`GET
 * /me/companies`). Links are deliberately full page loads: every workspace is
 * rendered fresh on the server for the chosen Company, nothing from the
 * previous Company stays in client state or the router cache, and the
 * unsaved-changes warning of the settings form applies. The id in the link is
 * only a resource identifier; the API authorizes the destination.
 */
export function CompanySwitcher({ currentId, items }: { currentId: string; items: SwitcherItem[] }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

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
    <div className="sm:relative">
      <button
        aria-controls={panelId}
        aria-expanded={open}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-hero-control bg-white px-4 text-sm font-bold text-hero-navy transition-colors duration-150 hover:bg-hero-blue-tint"
        onClick={() => setOpen((value) => !value)}
        ref={buttonRef}
        type="button"
      >
        {/* The narrowest phones show "Switch"; the accessible name stays "Switch company". */}
        <span>
          Switch <span className="max-[379px]:sr-only">company</span>
        </span>
        <ChevronDownIcon className={`size-4 transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div
          className="fade-swap absolute inset-x-4 top-full z-50 mt-2 rounded-2xl border border-hero-border bg-white p-2 shadow-hero-card-hover sm:inset-x-auto sm:right-0 sm:w-80"
          id={panelId}
          ref={panelRef}
        >
          <nav aria-label="Your companies">
            <ul className="flex flex-col">
              {items.map((item) => {
                const current = item.companyId === currentId;
                return (
                  <li key={item.companyId}>
                    <a
                      aria-current={current ? "page" : undefined}
                      className="flex min-h-11 items-center justify-between gap-3 rounded-xl px-3 py-2 text-[0.9375rem] font-semibold text-hero-navy hover:bg-hero-blue-tint aria-[current=page]:bg-hero-bg"
                      href={`/workspaces/${encodeURIComponent(item.companyId)}`}
                    >
                      <span className="min-w-0 break-words">{item.name}</span>
                      {current ? <CheckIcon className="size-4 shrink-0 text-hero-blue" /> : null}
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
