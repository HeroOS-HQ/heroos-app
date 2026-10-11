import "server-only";

import { type AuthConfig, parseHttpsUrl, signedOutUrl } from "./config";

/**
 * Authorization, token and sign-out endpoints for the configured provider.
 *
 * - `cognito`: the fixed managed-login paths (Cognito's discovery document does
 *   not describe its managed-login logout endpoint).
 * - `oidc`: standard OpenID Connect Discovery 1.0 metadata from
 *   `<issuer>/.well-known/openid-configuration`, accepted only when its `issuer`
 *   equals the configured issuer exactly, the authorization and token endpoints
 *   are https on the issuer's origin, and the provider supports the `code`
 *   response type and PKCE `S256`. Fetched without following redirects. Sign-out uses
 *   RP-Initiated Logout 1.0 (`client_id` + `post_logout_redirect_uri`) only when
 *   the `end_session_endpoint` is on the issuer's origin (the CSP allows only
 *   that origin); otherwise sign-out is local only.
 *
 * Metadata is cached in memory for an hour; failures are never cached and fail
 * closed (sign-in reports "unavailable").
 */

export type Endpoints = {
  authorization: URL;
  token: URL;
  /** Fully built provider sign-out URL, or null for local-only sign-out. */
  signOut: URL | null;
};

type Fetch = typeof fetch;
type Metadata = { authorization: URL; token: URL; endSession: URL | null };

export const DISCOVERY_TTL_MS = 60 * 60 * 1000;
const DISCOVERY_TIMEOUT_MS = 5_000;
const cache = new Map<string, { metadata: Metadata; expires: number }>();

export function clearDiscoveryCache(): void {
  cache.clear();
}

export function discoveryUrl(issuer: string): string {
  return `${issuer.replace(/\/+$/, "")}/.well-known/openid-configuration`;
}

/** Validate an OIDC discovery document for `issuer`; null when unacceptable. */
export function parseDiscovery(document: unknown, issuer: string, issuerOrigin: string): Metadata | null {
  if (typeof document !== "object" || document === null || Array.isArray(document)) return null;
  const doc = document as Record<string, unknown>;
  if (doc.issuer !== issuer) return null;
  const authorization = parseHttpsUrl(doc.authorization_endpoint);
  const token = parseHttpsUrl(doc.token_endpoint);
  if (authorization === null || token === null) return null;
  // Users are sent to, and the code + PKCE verifier are posted to, the
  // issuer's own origin only: a tampered or misconfigured document cannot
  // divert them to another host.
  if (authorization.origin !== issuerOrigin || token.origin !== issuerOrigin) return null;
  const responseTypes = doc.response_types_supported;
  if (!Array.isArray(responseTypes) || !responseTypes.includes("code")) return null;
  const pkce = doc.code_challenge_methods_supported;
  if (!Array.isArray(pkce) || !pkce.includes("S256")) return null;
  const endSession = parseHttpsUrl(doc.end_session_endpoint);
  return {
    authorization,
    token,
    endSession: endSession !== null && endSession.origin === issuerOrigin ? endSession : null,
  };
}

async function discover(
  issuer: string,
  issuerOrigin: string,
  fetcher: Fetch,
  now: number,
): Promise<Metadata | null> {
  const cached = cache.get(issuer);
  if (cached && cached.expires > now) return cached.metadata;
  try {
    const response = await fetcher(discoveryUrl(issuer), {
      headers: { Accept: "application/json" },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(DISCOVERY_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    const metadata = parseDiscovery(await response.json(), issuer, issuerOrigin);
    if (metadata !== null) cache.set(issuer, { metadata, expires: now + DISCOVERY_TTL_MS });
    return metadata;
  } catch {
    return null;
  }
}

export async function resolveEndpoints(
  config: AuthConfig,
  deps: { fetch: Fetch; now: () => number },
): Promise<Endpoints | null> {
  const provider = config.provider;
  if (provider.kind === "cognito") {
    const signOut = new URL("/logout", provider.origin);
    signOut.search = new URLSearchParams({
      client_id: config.clientId,
      logout_uri: signedOutUrl(config),
    }).toString();
    return {
      authorization: new URL("/oauth2/authorize", provider.origin),
      token: new URL("/oauth2/token", provider.origin),
      signOut,
    };
  }

  const metadata = await discover(provider.issuer, provider.origin, deps.fetch, deps.now());
  if (metadata === null) return null;
  let signOut: URL | null = null;
  if (metadata.endSession !== null) {
    signOut = new URL(metadata.endSession);
    signOut.searchParams.set("client_id", config.clientId);
    signOut.searchParams.set("post_logout_redirect_uri", signedOutUrl(config));
  }
  return { authorization: metadata.authorization, token: metadata.token, signOut };
}
