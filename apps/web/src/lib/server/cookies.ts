import "server-only";

/**
 * Cookie names and attributes for the browser session.
 *
 * `__Host-` prefix: the browser only accepts the cookie when it is `Secure`,
 * `Path=/` and has no `Domain`, so no other host or path can set or overwrite it.
 * `HttpOnly` keeps it out of JavaScript; `SameSite=Lax` keeps it off cross-site
 * subresource and POST requests while still arriving on the top-level redirect
 * back from Cognito.
 */

export const SESSION_COOKIE = "__Host-heroos-session";
export const LOGIN_COOKIE = "__Host-heroos-login";

export function serializeCookie(name: string, value: string, maxAgeSeconds: number): string {
  return `${name}=${value}; Path=/; Max-Age=${Math.max(0, Math.floor(maxAgeSeconds))}; HttpOnly; Secure; SameSite=Lax`;
}

export function expireCookie(name: string): string {
  return serializeCookie(name, "", 0);
}

export function readCookie(header: string | null, name: string): string | undefined {
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const index = part.indexOf("=");
    if (index > 0 && part.slice(0, index).trim() === name) {
      return part.slice(index + 1).trim();
    }
  }
  return undefined;
}
