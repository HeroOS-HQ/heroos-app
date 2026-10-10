/**
 * Content-Security-Policy for every HTML response, built per request in `proxy.ts`.
 *
 * Scripts and styles run only with the per-request nonce (Next.js applies it to
 * its own tags). `form-action` additionally allows the identity provider's
 * origin because the sign-out form redirects there. Nothing may frame the app.
 */

export type CspOptions = { nonce: string; identityProviderOrigin: string | null; development: boolean };

export function contentSecurityPolicy({ nonce, identityProviderOrigin, development }: CspOptions): string {
  const formAction = ["'self'", ...(identityProviderOrigin ? [identityProviderOrigin] : [])].join(" ");
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

/** Origin of an https URL with a concrete host, or null. */
function httpsOrigin(value: string | undefined, exactOrigin: boolean): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const concreteHost = /^[a-z0-9.-]+$/.test(url.hostname);
    if (url.protocol !== "https:" || !concreteHost) return null;
    return exactOrigin && url.origin !== value ? null : url.origin;
  } catch {
    return null;
  }
}

type Env = Record<string, string | undefined>;

/**
 * The configured identity provider's origin for `form-action`: the Cognito
 * managed-login origin, or the OIDC issuer's origin (the only origin the sign-out
 * redirect may target; see lib/server/provider-endpoints.ts). Null when unset or invalid.
 */
export function identityProviderOriginFrom(env: Env): string | null {
  switch (env.HEROOS_WEB_AUTH_PROVIDER) {
    case "cognito":
      return httpsOrigin(env.HEROOS_COGNITO_DOMAIN, true);
    case "oidc":
      return httpsOrigin(env.HEROOS_OIDC_ISSUER, false);
    default:
      return null;
  }
}
