import "server-only";

/**
 * Server-only web configuration for sign-in and the HeroOS API.
 *
 * Two identity providers share one flow (docs/architecture/authentication.md §10):
 * `cognito` (M5) and provider-neutral `oidc` (pre-M5 demo). Every value comes
 * from the runtime environment (never `NEXT_PUBLIC_`), so none is inlined into
 * browser JavaScript. Validation fails closed and reports variable names only,
 * never values. See docs/operations/demo-authentication-deployment.md.
 */

export type IdentityProvider =
  /** Cognito managed login; fixed endpoint paths on the managed-login origin. */
  | { kind: "cognito"; origin: string }
  /** Any OpenID Provider; endpoints come from OIDC discovery of `issuer`. */
  | { kind: "oidc"; issuer: string; origin: string; audience: string };

export type AuthConfig = {
  /** Exact public origin of this web app, e.g. https://heroos-demo.vercel.app */
  webOrigin: string;
  provider: IdentityProvider;
  /** Public client ID (no client secret: Authorization Code + PKCE). */
  clientId: string;
  /** HeroOS API base URL (Render), without trailing slash. */
  apiBaseUrl: string;
  /** The demo Company; access is still decided by the API's Membership check. */
  demoCompanyId: string;
  /** 32-byte key material for sealing cookies. */
  sessionSecret: Buffer;
};

export type ConfigResult =
  | { ok: true; config: AuthConfig }
  | { ok: false; invalid: string[] };

type Env = Record<string, string | undefined>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const COGNITO_CLIENT_ID = /^[A-Za-z0-9]{1,128}$/;
const OIDC_CLIENT_ID = /^[A-Za-z0-9._@:-]{1,256}$/;
const AUDIENCE = /^[\x21-\x7e]{1,512}$/;
const SESSION_SECRET = /^[0-9a-f]{64}$/;
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
// The URL parser accepts characters such as `*` in host names; origins here must
// be concrete DNS names (or bracketed IPv6 literals), never patterns.
const HOSTNAME = /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*|\[[0-9a-f:.]+\])$/;

/** Exact `scheme://host[:port]` origin; https, or http://localhost outside production. */
function parseOrigin(value: string | undefined, allowLocalHttp: boolean): string | null {
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const local = LOCAL_HOSTS.has(url.hostname);
  const schemeOk =
    url.protocol === "https:" || (url.protocol === "http:" && local && allowLocalHttp);
  if (!schemeOk || !HOSTNAME.test(url.hostname)) return null;
  if (url.username || url.password || url.origin !== value) return null;
  return url.origin;
}

/** https base URL (optionally with a path prefix), no query, fragment or trailing slash. */
function parseBaseUrl(value: string | undefined, allowLocalHttp: boolean): string | null {
  if (!value || value.endsWith("/")) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (parseOrigin(url.origin, allowLocalHttp) === null) return null;
  if (url.search || url.hash || url.username || url.password) return null;
  return value;
}

/** An https URL with a concrete host and no credentials, query or fragment. */
export function parseHttpsUrl(value: unknown): URL | null {
  if (typeof value !== "string" || !value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || !HOSTNAME.test(url.hostname)) return null;
  if (url.username || url.password || url.search || url.hash) return null;
  return url;
}

/**
 * The OIDC issuer identifier: an https URL compared verbatim with discovery and
 * with token `iss` (OIDC Discovery §4.3), so the configured string is kept as is
 * (a trailing slash, if the provider uses one, is significant).
 */
function parseIssuer(value: string | undefined): { issuer: string; origin: string } | null {
  const url = parseHttpsUrl(value);
  return url && value ? { issuer: value, origin: url.origin } : null;
}

function readProvider(env: Env, invalid: string[]): { provider: IdentityProvider; clientId: string } | null {
  switch (env.HEROOS_WEB_AUTH_PROVIDER) {
    case "cognito": {
      const origin = parseOrigin(env.HEROOS_COGNITO_DOMAIN, false);
      if (origin === null) invalid.push("HEROOS_COGNITO_DOMAIN");
      const clientId = env.HEROOS_COGNITO_CLIENT_ID ?? "";
      if (!COGNITO_CLIENT_ID.test(clientId)) invalid.push("HEROOS_COGNITO_CLIENT_ID");
      return origin === null ? null : { provider: { kind: "cognito", origin }, clientId };
    }
    case "oidc": {
      const issuer = parseIssuer(env.HEROOS_OIDC_ISSUER);
      if (issuer === null) invalid.push("HEROOS_OIDC_ISSUER");
      const clientId = env.HEROOS_OIDC_CLIENT_ID ?? "";
      if (!OIDC_CLIENT_ID.test(clientId)) invalid.push("HEROOS_OIDC_CLIENT_ID");
      const audience = env.HEROOS_OIDC_AUDIENCE ?? "";
      // The API audience must never be the client ID: that is an ID token's `aud`.
      if (!AUDIENCE.test(audience) || audience === clientId) invalid.push("HEROOS_OIDC_AUDIENCE");
      return issuer === null ? null : { provider: { kind: "oidc", ...issuer, audience }, clientId };
    }
    default:
      invalid.push("HEROOS_WEB_AUTH_PROVIDER");
      return null;
  }
}

export function readAuthConfig(env: Env = process.env): ConfigResult {
  const allowLocalHttp = env.NODE_ENV !== "production";
  const invalid: string[] = [];

  const webOrigin = parseOrigin(env.HEROOS_WEB_ORIGIN, allowLocalHttp);
  if (webOrigin === null) invalid.push("HEROOS_WEB_ORIGIN");
  const identity = readProvider(env, invalid);
  const apiBaseUrl = parseBaseUrl(env.HEROOS_API_BASE_URL, allowLocalHttp);
  if (apiBaseUrl === null) invalid.push("HEROOS_API_BASE_URL");
  const demoCompanyId = env.HEROOS_DEMO_COMPANY_ID ?? "";
  if (!UUID.test(demoCompanyId)) invalid.push("HEROOS_DEMO_COMPANY_ID");
  const secret = env.HEROOS_WEB_SESSION_SECRET ?? "";
  if (!SESSION_SECRET.test(secret)) invalid.push("HEROOS_WEB_SESSION_SECRET");
  // Node disables TLS certificate verification process-wide when this is "0";
  // discovery and the token exchange must never run that way.
  if (env.NODE_TLS_REJECT_UNAUTHORIZED === "0") invalid.push("NODE_TLS_REJECT_UNAUTHORIZED");

  if (invalid.length > 0 || identity === null) return { ok: false, invalid };
  return {
    ok: true,
    config: {
      webOrigin: webOrigin!,
      provider: identity.provider,
      clientId: identity.clientId,
      apiBaseUrl: apiBaseUrl!,
      demoCompanyId,
      sessionSecret: Buffer.from(secret, "hex"),
    },
  };
}

/** The OAuth redirect URI registered on the client. */
export function callbackUrl(config: AuthConfig): string {
  return `${config.webOrigin}/auth/callback`;
}

/** Where the provider returns after logout (registered as a sign-out URL). */
export function signedOutUrl(config: AuthConfig): string {
  return `${config.webOrigin}/`;
}
