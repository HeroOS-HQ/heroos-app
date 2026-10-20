import { type RefObject, useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal panel (the Cases drawer, the case status): while open, focus moves
 * into it and stays there (Tab wraps), Escape closes it, the page behind can't
 * scroll, and closing returns focus to the control that opened it. Client
 * components only.
 */
export function useModalPanel(
  open: boolean,
  onClose: () => void,
  panel: RefObject<HTMLElement | null>,
  /** The control that opens the panel: focus returns there (a click doesn't focus a button in every browser). */
  returnTo?: RefObject<HTMLElement | null>,
) {
  // The latest close handler, without re-running the effect (and refocusing) on every render.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    // Where focus goes back to on close: the opening control, else whatever had focus.
    const opener = returnTo?.current ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const root = document.documentElement;
    root.classList.add("ws-scroll-lock");

    const focusables = () => [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const frame = requestAnimationFrame(() => {
      const first = panel.current?.querySelector<HTMLElement>("[data-autofocus]") ?? focusables()[0] ?? panel.current;
      first?.focus();
    });

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);

    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      root.classList.remove("ws-scroll-lock");
      // Back to the control that opened the panel, if it is still on the page.
      if (opener?.isConnected) opener.focus();
    };
  }, [open, panel, returnTo]);
}
