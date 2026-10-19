// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CONFIG,
  COGNITO_ORIGIN,
  OIDC_AUDIENCE,
  OIDC_CONFIG,
  OIDC_ORIGIN,
  WEB_ORIGIN,
  cookieValue,
  discoveryDocument,
} from "@/test/fixtures";

import { completeLogin, isSameOriginRequest, sessionFromRequest, startLogin } from "./auth-flow";
import { LOGIN_COOKIE, SESSION_COOKIE } from "./cookies";
import { clearDiscoveryCache } from "./provider-endpoints";
import { seal, unseal } from "./sealed";

/**
 * M1-10D: "Get started" (hosted sign-up, then onboarding) on top of the
 * existing Authorization Code + PKCE flow. The intent is sealed in the login
 * cookie and maps to one fixed landing path; nothing comes from the request.
 */

const NOW = 1_800_000_000_000;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function provider() {
  const fetchMock = vi.fn(async (input: string | URL) => {
    const url = input.toString();
    if (url.endsWith("/.well-known/openid-configuration")) return json(discoveryDocument());
    return json({ access_token: "header.token.signature", token_type: "Bearer", expires_in: 900 });
  });
  return { fetch: fetchMock as unknown as typeof fetch, now: () => NOW };
}

beforeEach(() => clearDiscoveryCache());

async function signIn(config: typeof CONFIG, intent?: "login" | "signup", query: Record<string, string> = {}) {
  const deps = provider();
  const started = await startLogin(config, deps, intent);
  const location = new URL(started.headers.get("location")!);
  const loginCookie = cookieValue(started, LOGIN_COOKIE)!;
  const url = new URL("/auth/callback", WEB_ORIGIN);
  url.search = new URLSearchParams({ code: "code", state: location.searchParams.get("state")!, ...query }).toString();
  const finished = await completeLogin(new Request(url, { headers: { cookie: `${LOGIN_COOKIE}=${loginCookie}` } }), config, deps);
  return { location, loginCookie, finished };
}

describe("hosted sign-up entry", () => {
  it("asks an OpenID Provider for its sign-up screen with a fixed hint, keeping PKCE and the audience", async () => {
    const { location, loginCookie } = await signIn(OIDC_CONFIG, "signup");
    expect(location.origin + location.pathname).toBe(`${OIDC_ORIGIN}/authorize`);
    expect(Object.fromEntries(location.searchParams)).toMatchObject({
      response_type: "code",
      code_challenge_method: "S256",
      audience: OIDC_AUDIENCE,
      screen_hint: "signup",
    });
    expect(unseal(loginCookie, OIDC_CONFIG.sessionSecret, "login")).toMatchObject({ intent: "signup" });
  });

  it("a normal sign-in carries no sign-up hint", async () => {
    const { location } = await signIn(OIDC_CONFIG, "login");
    expect(location.searchParams.has("screen_hint")).toBe(false);
  });

  it("opens Cognito's managed login unchanged (no provider-specific hint)", async () => {
    const { location } = await signIn(CONFIG, "signup");
    expect(location.origin + location.pathname).toBe(`${COGNITO_ORIGIN}/oauth2/authorize`);
    expect(location.searchParams.has("screen_hint")).toBe(false);
  });

  it("lands a new founder on onboarding and a returning user on the homepage", async () => {
    expect((await signIn(OIDC_CONFIG, "signup")).finished.headers.get("location")).toBe(
      `${WEB_ORIGIN}/onboarding?start=signup`,
    );
    expect((await signIn(OIDC_CONFIG, "login")).finished.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
    expect((await signIn(OIDC_CONFIG)).finished.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
  });

  it("never takes the landing path or the intent from the callback request", async () => {
    const { finished } = await signIn(OIDC_CONFIG, "login", {
      intent: "signup",
      redirect_uri: "https://evil.example.com/",
      next: "//evil.example.com",
    });
    expect(finished.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
  });

  it("a login cookie sealed before M1-10D (no intent) is a sign-in", async () => {
    const deps = provider();
    const started = await startLogin(OIDC_CONFIG, deps);
    const state = new URL(started.headers.get("location")!).searchParams.get("state")!;
    const legacy = seal({ state, verifier: "v".repeat(43), exp: NOW / 1000 + 600 }, OIDC_CONFIG.sessionSecret, "login");
    const url = new URL("/auth/callback", WEB_ORIGIN);
    url.search = new URLSearchParams({ code: "code", state }).toString();
    const finished = await completeLogin(new Request(url, { headers: { cookie: `${LOGIN_COOKIE}=${legacy}` } }), OIDC_CONFIG, deps);
    expect(finished.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
  });
});

describe("isSameOriginRequest (CSRF for logout and BFF mutations)", () => {
  const request = (headers: Record<string, string>) => new Request(`${WEB_ORIGIN}/bff/registrations`, { method: "POST", headers });

  it.each([
    [{ origin: WEB_ORIGIN }, true],
    [{ origin: WEB_ORIGIN, "sec-fetch-site": "same-origin" }, true],
    [{ origin: "null", "sec-fetch-site": "same-origin" }, true],
    [{ "sec-fetch-site": "same-origin" }, true],
    [{ origin: "https://evil.example.com" }, false],
    [{ origin: "https://evil.example.com", "sec-fetch-site": "same-origin" }, false],
    [{ origin: "null", "sec-fetch-site": "cross-site" }, false],
    [{ origin: "null" }, false],
    [{ "sec-fetch-site": "same-site" }, false],
    [{}, false],
    [{ origin: `${WEB_ORIGIN}.evil.example.com` }, false],
  ])("%o → %s", (headers, expected) => {
    expect(isSameOriginRequest(request(headers), CONFIG)).toBe(expected);
  });
});

describe("sessionFromRequest", () => {
  const withCookie = (value: string) => new Request(`${WEB_ORIGIN}/bff/registrations`, { headers: { cookie: `a=b; ${SESSION_COOKIE}=${value}` } });
  const now = NOW / 1000;

  it("reads a valid sealed session", () => {
    const sealed = seal({ accessToken: "token", exp: now + 60 }, CONFIG.sessionSecret, "session");
    expect(sessionFromRequest(withCookie(sealed), CONFIG, now)).toEqual({ accessToken: "token", exp: now + 60 });
  });

  it("refuses an expired, tampered, foreign-purpose or missing session", () => {
    const expired = seal({ accessToken: "token", exp: now - 1 }, CONFIG.sessionSecret, "session");
    const login = seal({ accessToken: "token", exp: now + 60 }, CONFIG.sessionSecret, "login");
    const valid = seal({ accessToken: "token", exp: now + 60 }, CONFIG.sessionSecret, "session");
    expect(sessionFromRequest(withCookie(expired), CONFIG, now)).toBeNull();
    expect(sessionFromRequest(withCookie(login), CONFIG, now)).toBeNull();
    expect(sessionFromRequest(withCookie(`${valid.slice(0, -2)}xx`), CONFIG, now)).toBeNull();
    expect(sessionFromRequest(new Request(WEB_ORIGIN), CONFIG, now)).toBeNull();
  });
});
