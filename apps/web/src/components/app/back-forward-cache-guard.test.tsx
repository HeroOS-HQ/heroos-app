import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./app-shell";
import { BackForwardCacheGuard } from "./back-forward-cache-guard";

function pageTransition(type: "pagehide" | "pageshow", persisted: boolean): Event {
  const event = new Event(type);
  Object.defineProperty(event, "persisted", { value: persisted });
  return event;
}

function stubReload() {
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  return reload;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-restoring");
});

describe("BackForwardCacheGuard", () => {
  it("hides a signed-in page as it enters the back/forward cache and reloads it if restored", () => {
    const reload = stubReload();
    render(<BackForwardCacheGuard />);

    window.dispatchEvent(pageTransition("pagehide", true));
    expect(document.documentElement.hasAttribute("data-restoring")).toBe(true);

    window.dispatchEvent(pageTransition("pageshow", true));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("leaves ordinary loads and unloads alone", () => {
    const reload = stubReload();
    render(<BackForwardCacheGuard />);

    window.dispatchEvent(pageTransition("pageshow", false));
    window.dispatchEvent(pageTransition("pagehide", false));
    expect(reload).not.toHaveBeenCalled();
    expect(document.documentElement.hasAttribute("data-restoring")).toBe(false);
  });

  it("is part of every signed-in page, and only those", () => {
    const reload = stubReload();
    const { unmount } = render(<AppShell signedIn={false}>x</AppShell>);
    window.dispatchEvent(pageTransition("pageshow", true));
    expect(reload).not.toHaveBeenCalled();
    unmount();

    render(<AppShell>x</AppShell>);
    window.dispatchEvent(pageTransition("pageshow", true));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
