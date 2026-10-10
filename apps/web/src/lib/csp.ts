/**
 * Content-Security-Policy for every HTML response, built per request in `proxy.ts`.
 *
 * Scripts and styles run only with the per-request nonce (Next.js applies it to
 * its own tags). `form-action` additionally allows the Cognito origin because the
 * sign-out form redirects there. Nothing may frame the app.
 */

export type CspOptions = { nonce: string; cognitoOrigin: string | null; development: boolean };

export function contentSecurityPolicy({ nonce, cognitoOrigin, development }: CspOptions): string {
  const formAction = ["'self'", ...(cognitoOrigin ? [cognitoOrigin] : [])].join(" ");
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    `form-action ${formAction}`,
    "frame-ancestors 'none'",
    ...(development ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

/** The Cognito origin for `form-action`, or null when unset or not an https origin. */
export function cognitoOriginFrom(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const concreteHost = /^[a-z0-9.-]+$/.test(url.hostname);
    return url.protocol === "https:" && concreteHost && url.origin === value ? url.origin : null;
  } catch {
    return null;
  }
}
