import type { AuthConfig } from "@/lib/server/config";

export const WEB_ORIGIN = "https://heroos-demo.example.com";
export const COGNITO_ORIGIN = "https://heroos-demo.auth.eu-west-1.amazoncognito.com";
export const API_BASE_URL = "https://heroos-api.example.com";
export const CLIENT_ID = "abc123clientid";
export const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";
export const SESSION_SECRET_HEX = "0f".repeat(32);

// Provider-neutral OIDC (an Auth0-style issuer with a trailing slash).
export const OIDC_ISSUER = "https://heroos-demo.idp.example.com/";
export const OIDC_ORIGIN = "https://heroos-demo.idp.example.com";
export const OIDC_CLIENT_ID = "oidcWebClient123";
export const OIDC_AUDIENCE = "https://api.heroos-demo.example.com";

const COMMON_ENV = {
  NODE_ENV: "production",
  HEROOS_WEB_ORIGIN: WEB_ORIGIN,
  HEROOS_API_BASE_URL: API_BASE_URL,
  HEROOS_DEMO_COMPANY_ID: COMPANY_ID,
  HEROOS_WEB_SESSION_SECRET: SESSION_SECRET_HEX,
};

export const ENV = {
  ...COMMON_ENV,
  HEROOS_WEB_AUTH_PROVIDER: "cognito",
  HEROOS_COGNITO_DOMAIN: COGNITO_ORIGIN,
  HEROOS_COGNITO_CLIENT_ID: CLIENT_ID,
};

export const OIDC_ENV = {
  ...COMMON_ENV,
  HEROOS_WEB_AUTH_PROVIDER: "oidc",
  HEROOS_OIDC_ISSUER: OIDC_ISSUER,
  HEROOS_OIDC_CLIENT_ID: OIDC_CLIENT_ID,
  HEROOS_OIDC_AUDIENCE: OIDC_AUDIENCE,
};

const COMMON_CONFIG = {
  webOrigin: WEB_ORIGIN,
  apiBaseUrl: API_BASE_URL,
  demoCompanyId: COMPANY_ID,
  sessionSecret: Buffer.from(SESSION_SECRET_HEX, "hex"),
};

/** Cognito (M5) configuration. */
export const CONFIG: AuthConfig = {
  ...COMMON_CONFIG,
  provider: { kind: "cognito", origin: COGNITO_ORIGIN },
  clientId: CLIENT_ID,
};

export const OIDC_CONFIG: AuthConfig = {
  ...COMMON_CONFIG,
  provider: { kind: "oidc", issuer: OIDC_ISSUER, origin: OIDC_ORIGIN, audience: OIDC_AUDIENCE },
  clientId: OIDC_CLIENT_ID,
};

/** A valid OIDC discovery document for OIDC_ISSUER. */
export function discoveryDocument(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    issuer: OIDC_ISSUER,
    authorization_endpoint: `${OIDC_ORIGIN}/authorize`,
    token_endpoint: `${OIDC_ORIGIN}/oauth/token`,
    end_session_endpoint: `${OIDC_ORIGIN}/oidc/logout`,
    jwks_uri: `${OIDC_ORIGIN}/.well-known/jwks.json`,
    response_types_supported: ["code", "token", "id_token"],
    code_challenge_methods_supported: ["S256", "plain"],
    ...overrides,
  };
}

/** All Set-Cookie header values of a response. */
export function setCookies(response: Response): string[] {
  return response.headers.getSetCookie();
}

/** The value of cookie `name` from a response's Set-Cookie headers. */
export function cookieValue(response: Response, name: string): string | undefined {
  const header = setCookies(response).find((cookie) => cookie.startsWith(`${name}=`));
  return header?.slice(name.length + 1).split(";")[0];
}
