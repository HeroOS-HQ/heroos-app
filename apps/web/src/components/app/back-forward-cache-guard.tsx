"use client";

import { useEffect } from "react";

/**
 * Signed-in pages must never come back from the browser's back/forward cache:
 * after a sign-out on a shared device, Back would show the previous person's
 * Company data again. Self-hosted, Next.js sends `no-store` for these pages,
 * which keeps them out of that cache. A hosting platform may send other caching
 * headers (the live Vercel deployment sends `public, max-age=0,
 * must-revalidate`; M1-10E), so the page also refuses to be restored: it hides
 * itself when it is put into the cache and, if it is ever restored, reloads, so
 * the server checks the session again.
 */
export function BackForwardCacheGuard() {
  useEffect(() => {
    const onPageHide = (event: PageTransitionEvent) => {
      if (event.persisted) document.documentElement.setAttribute("data-restoring", "");
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) window.location.reload();
    };
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, []);
  return null;
}
