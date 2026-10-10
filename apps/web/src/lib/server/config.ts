import "server-only";

/**
 * Server-only web configuration for the Cognito sign-in flow and the HeroOS API.
 *
 * Every value comes from the runtime environment (never `NEXT_PUBLIC_`), so none
 * is inlined into browser JavaScript. Validation fails closed and reports
 * variable names only, never values. See docs/operations/demo-authentication-deployment.md.
 */

export type AuthConfig = {
  /** Exact public origin of this web app, e.g. https://heroos-demo.vercel.app */
  webOrigin: string;
  /** Cognito managed-login origin, e.g. https://<prefix>.auth.eu-west-1.amazoncognito.com */
  cognitoOrigin: string;
  /** Public App Client ID (no client secret: Authorization Code + PKCE). */
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
const CLIENT_ID = /^[A-Za-z0-9]{1,128}$/;
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

export function readAuthConfig(env: Env = process.env): ConfigResult {
  const allowLocalHttp = env.NODE_ENV !== "production";
  const invalid: string[] = [];

  const webOrigin = parseOrigin(env.HEROOS_WEB_ORIGIN, allowLocalHttp);
  if (webOrigin === null) invalid.push("HEROOS_WEB_ORIGIN");
  const cognitoOrigin = parseOrigin(env.HEROOS_COGNITO_DOMAIN, false);
  if (cognitoOrigin === null) invalid.push("HEROOS_COGNITO_DOMAIN");
  const clientId = env.HEROOS_COGNITO_CLIENT_ID ?? "";
  if (!CLIENT_ID.test(clientId)) invalid.push("HEROOS_COGNITO_CLIENT_ID");
  const apiBaseUrl = parseBaseUrl(env.HEROOS_API_BASE_URL, allowLocalHttp);
  if (apiBaseUrl === null) invalid.push("HEROOS_API_BASE_URL");
  const demoCompanyId = env.HEROOS_DEMO_COMPANY_ID ?? "";
  if (!UUID.test(demoCompanyId)) invalid.push("HEROOS_DEMO_COMPANY_ID");
  const secret = env.HEROOS_WEB_SESSION_SECRET ?? "";
  if (!SESSION_SECRET.test(secret)) invalid.push("HEROOS_WEB_SESSION_SECRET");

  if (invalid.length > 0) return { ok: false, invalid };
  return {
    ok: true,
    config: {
      webOrigin: webOrigin!,
      cognitoOrigin: cognitoOrigin!,
      clientId,
      apiBaseUrl: apiBaseUrl!,
      demoCompanyId,
      sessionSecret: Buffer.from(secret, "hex"),
    },
  };
}

/** The OAuth redirect URI registered on the Cognito App Client. */
export function callbackUrl(config: AuthConfig): string {
  return `${config.webOrigin}/auth/callback`;
}

/** Where Cognito returns after logout (registered as a sign-out URL). */
export function signedOutUrl(config: AuthConfig): string {
  return `${config.webOrigin}/`;
}
