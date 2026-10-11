// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import { identityProviderOriginFrom } from "@/lib/csp";
import {
  CONFIG,
  OIDC_AUDIENCE,
  OIDC_CLIENT_ID,
  OIDC_CONFIG,
  OIDC_ENV,
  OIDC_ISSUER,
  OIDC_ORIGIN,
  WEB_ORIGIN,
  cookieValue,
  discoveryDocument,
  setCookies,
} from "@/test/fixtures";

import { completeLogin, logout, parseSession, startLogin } from "./auth-flow";
import { readAuthConfig } from "./config";
import { LOGIN_COOKIE, SESSION_COOKIE } from "./cookies";
import { codeChallenge } from "./pkce";
import {
  DISCOVERY_TTL_MS,
  clearDiscoveryCache,
  discoveryUrl,
  parseDiscovery,
  resolveEndpoints,
} from "./provider-endpoints";
import { unseal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.oidc-access-token.signature";
const DISCOVERY = "https://heroos-demo.idp.example.com/.well-known/openid-configuration";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A fetch stub routing discovery and token requests. */
function idp(options: { discovery?: () => Response | Error; token?: () => Response } = {}) {
  const fetchMock = vi.fn<(input: string | URL, init?: RequestInit) => Promise<Response>>(async (input) => {
    const url = input.toString();
    if (url === DISCOVERY) {
      const result = options.discovery ? options.discovery() : json(discoveryDocument());
      if (result instanceof Error) throw result;
      return result;
    }
    if (url === `${OIDC_ORIGIN}/oauth/token`) {
      return options.token
        ? options.token()
        : json({ access_token: ACCESS_TOKEN, id_token: "id", token_type: "Bearer", expires_in: 900 });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => NOW };
}

beforeEach(() => clearDiscoveryCache());

describe("OIDC discovery", () => {
  it("builds the well-known URL from the issuer", () => {
    expect(discoveryUrl(OIDC_ISSUER)).toBe(DISCOVERY);
    expect(discoveryUrl("https://idp.example.com/realms/heroos")).toBe(
      "https://idp.example.com/realms/heroos/.well-known/openid-configuration",
    );
  });

  it("accepts a valid document", () => {
    const metadata = parseDiscovery(discoveryDocument(), OIDC_ISSUER, OIDC_ORIGIN)!;
    expect(metadata.authorization.toString()).toBe(`${OIDC_ORIGIN}/authorize`);
    expect(metadata.token.toString()).toBe(`${OIDC_ORIGIN}/oauth/token`);
    expect(metadata.endSession!.toString()).toBe(`${OIDC_ORIGIN}/oidc/logout`);
  });

  it.each([
    ["issuer mismatch", { issuer: "https://evil.example.com/" }],
    ["issuer without the trailing slash", { issuer: OIDC_ISSUER.slice(0, -1) }],
    ["http authorization endpoint", { authorization_endpoint: "http://heroos-demo.idp.example.com/authorize" }],
    ["http token endpoint", { token_endpoint: "http://heroos-demo.idp.example.com/oauth/token" }],
    ["missing token endpoint", { token_endpoint: undefined }],
    ["no code response type", { response_types_supported: ["token"] }],
    ["no PKCE support listed", { code_challenge_methods_supported: undefined }],
    ["PKCE plain only", { code_challenge_methods_supported: ["plain"] }],
  ])("rejects a document with %s", (_, overrides) => {
    expect(parseDiscovery(discoveryDocument(overrides), OIDC_ISSUER, OIDC_ORIGIN)).toBeNull();
  });

  it.each([[null], [[]], ["string"], [42]])("rejects a non-object document %j", (document) => {
    expect(parseDiscovery(document, OIDC_ISSUER, OIDC_ORIGIN)).toBeNull();
  });

  it.each([
    ["missing", undefined],
    ["on another origin", "https://logout.other.example.com/logout"],
    ["not https", "http://heroos-demo.idp.example.com/oidc/logout"],
  ])("falls back to local sign-out when end_session_endpoint is %s", (_, endSession) => {
    const metadata = parseDiscovery(discoveryDocument({ end_session_endpoint: endSession }), OIDC_ISSUER, OIDC_ORIGIN);
    expect(metadata).not.toBeNull();
    expect(metadata!.endSession).toBeNull();
  });

  it("caches a valid document and never caches failures", async () => {
    let calls = 0;
    const failing = idp({ discovery: () => (++calls === 1 ? new Error("ECONNRESET") : json(discoveryDocument())) });
    expect(await resolveEndpoints(OIDC_CONFIG, failing)).toBeNull();
    expect(await resolveEndpoints(OIDC_CONFIG, failing)).not.toBeNull();
    expect(await resolveEndpoints(OIDC_CONFIG, failing)).not.toBeNull();
    expect(failing.fetchMock).toHaveBeenCalledTimes(2);

    const later = { ...failing, now: () => NOW + DISCOVERY_TTL_MS + 1 };
    await resolveEndpoints(OIDC_CONFIG, later);
    expect(failing.fetchMock).toHaveBeenCalledTimes(3);
  });

  it("fetches discovery without caching or following redirects", async () => {
    const provider = idp();
    await resolveEndpoints(OIDC_CONFIG, provider);
    const init = provider.fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("error");
  });

  it.each([
    ["HTTP 500", () => json({}, 500)],
    ["invalid JSON", () => new Response("<html>")],
    ["invalid document", () => json(discoveryDocument({ issuer: "https://evil.example.com/" }))],
  ])("returns no endpoints on %s", async (_, discovery) => {
    expect(await resolveEndpoints(OIDC_CONFIG, idp({ discovery }))).toBeNull();
  });

  it("never fetches anything for Cognito", async () => {
    const provider = idp();
    const endpoints = await resolveEndpoints(CONFIG, provider);
    expect(endpoints!.authorization.pathname).toBe("/oauth2/authorize");
    expect(provider.fetchMock).not.toHaveBeenCalled();
  });
});

describe("OIDC sign-in", () => {
  async function begin() {
    const provider = idp();
    const response = await startLogin(OIDC_CONFIG, provider);
    const location = new URL(response.headers.get("location")!);
    return { response, location, loginCookie: cookieValue(response, LOGIN_COOKIE)!, provider };
  }

  it("redirects to the discovered authorization endpoint with PKCE and the API audience", async () => {
    const { response, location, loginCookie } = await begin();
    expect(response.status).toBe(302);
    expect(location.origin + location.pathname).toBe(`${OIDC_ORIGIN}/authorize`);
    expect(Object.fromEntries(location.searchParams)).toMatchObject({
      response_type: "code",
      client_id: OIDC_CLIENT_ID,
      redirect_uri: `${WEB_ORIGIN}/auth/callback`,
      scope: "openid",
      code_challenge_method: "S256",
      audience: OIDC_AUDIENCE,
    });
    const transaction = unseal(loginCookie, OIDC_CONFIG.sessionSecret, "login") as Record<string, string>;
    expect(codeChallenge(transaction.verifier)).toBe(location.searchParams.get("code_challenge"));
  });

  it("reports unavailable without setting any cookie when discovery fails", async () => {
    const response = await startLogin(OIDC_CONFIG, idp({ discovery: () => new Error("down") }));
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=unavailable`);
    expect(setCookies(response)).toEqual([]);
  });

  it("exchanges the code at the discovered token endpoint and keeps only the access token", async () => {
    const { location, loginCookie, provider } = await begin();
    const state = location.searchParams.get("state")!;
    const url = new URL("/auth/callback", WEB_ORIGIN);
    url.search = new URLSearchParams({ code: "auth-code", state }).toString();
    const response = await completeLogin(
      new Request(url, { headers: { cookie: `${LOGIN_COOKIE}=${loginCookie}` } }),
      OIDC_CONFIG,
      provider,
    );

    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
    const tokenCall = provider.fetchMock.mock.calls.find(([u]) => u.toString().endsWith("/oauth/token"))!;
    const body = new URLSearchParams((tokenCall[1] as RequestInit).body as URLSearchParams);
    expect(body.get("client_id")).toBe(OIDC_CLIENT_ID);
    expect(body.get("grant_type")).toBe("authorization_code");
    const session = parseSession(unseal(cookieValue(response, SESSION_COOKIE), OIDC_CONFIG.sessionSecret, "session"), NOW / 1000);
    expect(session).toEqual({ accessToken: ACCESS_TOKEN, exp: NOW / 1000 + 900 });
    // Only the access token is stored: the decrypted session has no other field.
    const stored = unseal(cookieValue(response, SESSION_COOKIE), OIDC_CONFIG.sessionSecret, "session");
    expect(Object.keys(stored as object).sort()).toEqual(["accessToken", "exp"]);
  });

  it("still rejects a mismatched state before any provider contact", async () => {
    const { loginCookie } = await begin();
    const provider = idp();
    const url = new URL("/auth/callback", WEB_ORIGIN);
    url.search = new URLSearchParams({ code: "c", state: "forged" }).toString();
    const response = await completeLogin(
      new Request(url, { headers: { cookie: `${LOGIN_COOKIE}=${loginCookie}` } }),
      OIDC_CONFIG,
      provider,
    );
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
    expect(setCookies(response)).toEqual([]);
    expect(provider.fetchMock).not.toHaveBeenCalled();
  });
});

describe("OIDC sign-out", () => {
  const post = (headers: Record<string, string>) =>
    new Request(`${WEB_ORIGIN}/auth/logout`, { method: "POST", headers });

  it("uses RP-Initiated Logout with client_id and post_logout_redirect_uri", async () => {
    const response = await logout(post({ origin: WEB_ORIGIN }), OIDC_CONFIG, idp());
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location")!);
    expect(location.origin + location.pathname).toBe(`${OIDC_ORIGIN}/oidc/logout`);
    expect(Object.fromEntries(location.searchParams)).toEqual({
      client_id: OIDC_CLIENT_ID,
      post_logout_redirect_uri: `${WEB_ORIGIN}/`,
    });
    expect(setCookies(response).filter((c) => c.includes("Max-Age=0"))).toHaveLength(2);
  });

  it.each([
    ["no end_session_endpoint", () => json(discoveryDocument({ end_session_endpoint: undefined }))],
    ["an end_session_endpoint on another origin", () => json(discoveryDocument({ end_session_endpoint: "https://evil.example.com/logout" }))],
    ["an unreachable provider", () => new Error("down")],
  ])("signs out locally with %s", async (_, discovery) => {
    const response = await logout(post({ origin: WEB_ORIGIN }), OIDC_CONFIG, idp({ discovery }));
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
    expect(setCookies(response).filter((c) => c.includes("Max-Age=0"))).toHaveLength(2);
  });

  it("still refuses cross-site logout without contacting the provider", async () => {
    const provider = idp();
    const response = await logout(post({ origin: "https://evil.example.com" }), OIDC_CONFIG, provider);
    expect(response.status).toBe(403);
    expect(provider.fetchMock).not.toHaveBeenCalled();
  });
});

describe("CSP identity-provider origin", () => {
  it("allows the OIDC issuer's origin for the sign-out form", () => {
    expect(identityProviderOriginFrom(OIDC_ENV)).toBe(OIDC_ORIGIN);
  });

  it.each([undefined, "http://idp.example.com/", "https://*.example.com/", "nope"])(
    "allows nothing extra for an invalid issuer %s",
    (issuer) => {
      expect(identityProviderOriginFrom({ ...OIDC_ENV, HEROOS_OIDC_ISSUER: issuer })).toBeNull();
    },
  );

  it("allows nothing extra without a provider", () => {
    expect(identityProviderOriginFrom({})).toBeNull();
  });
});

describe("OIDC discovery hardening", () => {
  it.each([
    ["authorization endpoint on another host", { authorization_endpoint: "https://login.attacker.example/authorize" }],
    ["token endpoint on another host", { token_endpoint: "https://tokens.attacker.example/oauth/token" }],
    ["token endpoint on a look-alike host", { token_endpoint: "https://heroos-demo.idp.example.com.attacker.example/oauth/token" }],
    ["token endpoint on another port", { token_endpoint: "https://heroos-demo.idp.example.com:8443/oauth/token" }],
  ])("rejects a document with the %s", (_, overrides) => {
    expect(parseDiscovery(discoveryDocument(overrides), OIDC_ISSUER, OIDC_ORIGIN)).toBeNull();
  });

  it("never sends the code or verifier to a diverted token endpoint", async () => {
    const provider = idp({ discovery: () => json(discoveryDocument({ token_endpoint: "https://tokens.attacker.example/oauth/token" })) });
    const response = await startLogin(OIDC_CONFIG, provider);
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=unavailable`);
    expect(provider.fetchMock.mock.calls.map(([u]) => u.toString())).toEqual([DISCOVERY]);
  });

  it("accepts Auth0-shaped metadata without an end_session_endpoint (local sign-out)", () => {
    // Shape of https://samples.auth0.com/.well-known/openid-configuration (checked 2026-10-11).
    const metadata = parseDiscovery(discoveryDocument({ end_session_endpoint: undefined }), OIDC_ISSUER, OIDC_ORIGIN);
    expect(metadata).not.toBeNull();
    expect(metadata!.endSession).toBeNull();
  });
});

describe("TLS verification guard", () => {
  it("refuses to run sign-in with certificate verification disabled", () => {
    expect(readAuthConfig({ ...OIDC_ENV, NODE_TLS_REJECT_UNAUTHORIZED: "0" })).toEqual({
      ok: false,
      invalid: ["NODE_TLS_REJECT_UNAUTHORIZED"],
    });
    expect(readAuthConfig({ ...OIDC_ENV, NODE_TLS_REJECT_UNAUTHORIZED: "1" }).ok).toBe(true);
  });
});
