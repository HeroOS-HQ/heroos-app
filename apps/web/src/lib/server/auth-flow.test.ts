// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { CONFIG, COGNITO_ORIGIN, WEB_ORIGIN, cookieValue, setCookies } from "@/test/fixtures";

import {
  LOGIN_TTL_SECONDS,
  MAX_SESSION_SECONDS,
  completeLogin,
  logout,
  parseSession,
  startLogin,
} from "./auth-flow";
import { LOGIN_COOKIE, SESSION_COOKIE } from "./cookies";
import { codeChallenge, createState } from "./pkce";
import { unseal } from "./sealed";

const NOW = 1_800_000_000_000;
const ACCESS_TOKEN = "header.access-token-payload.signature";
const ID_TOKEN = "header.id-token-payload.signature";
const REFRESH_TOKEN = "refresh-token-opaque-value";

function tokenResponse(body: Record<string, unknown> = {}, status = 200): Response {
  return new Response(
    JSON.stringify({
      access_token: ACCESS_TOKEN,
      id_token: ID_TOKEN,
      refresh_token: REFRESH_TOKEN,
      token_type: "Bearer",
      expires_in: 3600,
      ...body,
    }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

function deps(response: Response | Error = tokenResponse(), now = NOW) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  return { fetch: fetchMock as unknown as typeof fetch, fetchMock, now: () => now };
}

/** Run startLogin and return the state and the login cookie a browser would hold. */
async function beginLogin(now = NOW) {
  const response = await startLogin(CONFIG, deps(tokenResponse(), now));
  const location = new URL(response.headers.get("location")!);
  return {
    response,
    location,
    state: location.searchParams.get("state")!,
    loginCookie: cookieValue(response, LOGIN_COOKIE)!,
  };
}

function callback(query: Record<string, string>, loginCookie?: string): Request {
  const url = new URL("/auth/callback", WEB_ORIGIN);
  url.search = new URLSearchParams(query).toString();
  const headers = loginCookie ? { cookie: `other=1; ${LOGIN_COOKIE}=${loginCookie}` } : undefined;
  return new Request(url, { headers });
}

describe("startLogin", () => {
  it("redirects to Cognito with Authorization Code + PKCE (S256)", async () => {
    const { response, location, loginCookie } = await beginLogin();
    expect(response.status).toBe(302);
    expect(location.origin + location.pathname).toBe(`${COGNITO_ORIGIN}/oauth2/authorize`);
    expect(Object.fromEntries(location.searchParams)).toMatchObject({
      response_type: "code",
      client_id: CONFIG.clientId,
      redirect_uri: `${WEB_ORIGIN}/auth/callback`,
      scope: "openid",
      code_challenge_method: "S256",
    });

    const transaction = unseal(loginCookie, CONFIG.sessionSecret, "login") as Record<string, unknown>;
    expect(transaction.state).toBe(location.searchParams.get("state"));
    expect(codeChallenge(transaction.verifier as string)).toBe(location.searchParams.get("code_challenge"));
    expect(location.toString()).not.toContain(transaction.verifier as string);
  });

  it("stores the transaction in a short-lived __Host- HttpOnly cookie", async () => {
    const [cookie] = setCookies((await beginLogin()).response);
    expect(cookie.startsWith(`${LOGIN_COOKIE}=`)).toBe(true);
    for (const attribute of ["Path=/", `Max-Age=${LOGIN_TTL_SECONDS}`, "HttpOnly", "Secure", "SameSite=Lax"]) {
      expect(cookie).toContain(attribute);
    }
    expect(cookie).not.toContain("Domain=");
  });

  it("creates a new state and verifier per login", async () => {
    expect((await beginLogin()).state).not.toBe((await beginLogin()).state);
  });
});

describe("completeLogin", () => {
  it("exchanges the code server-side and stores only the access token", async () => {
    const { state, loginCookie } = await beginLogin();
    const d = deps();
    const response = await completeLogin(callback({ code: "auth-code", state }, loginCookie), CONFIG, d);

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
    expect(response.headers.get("cache-control")).toBe("no-store");

    const [url, init] = d.fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.toString()).toBe(`${COGNITO_ORIGIN}/oauth2/token`);
    expect(init.method).toBe("POST");
    const body = new URLSearchParams(init.body as URLSearchParams);
    const transaction = unseal(loginCookie, CONFIG.sessionSecret, "login") as Record<string, string>;
    expect(Object.fromEntries(body)).toEqual({
      grant_type: "authorization_code",
      client_id: CONFIG.clientId,
      code: "auth-code",
      redirect_uri: `${WEB_ORIGIN}/auth/callback`,
      code_verifier: transaction.verifier,
    });

    const sessionCookie = cookieValue(response, SESSION_COOKIE)!;
    expect(parseSession(unseal(sessionCookie, CONFIG.sessionSecret, "session"), NOW / 1000)).toEqual({
      accessToken: ACCESS_TOKEN,
      exp: NOW / 1000 + 3600,
    });
    const allCookies = setCookies(response).join("\n");
    for (const secret of [ACCESS_TOKEN, ID_TOKEN, REFRESH_TOKEN]) {
      expect(allCookies).not.toContain(secret);
    }
    expect(setCookies(response).find((c) => c.startsWith(`${LOGIN_COOKIE}=`))).toContain("Max-Age=0");
    expect(setCookies(response).find((c) => c.startsWith(`${SESSION_COOKIE}=`))).toContain("HttpOnly");
  });

  it("caps the session lifetime", async () => {
    const { state, loginCookie } = await beginLogin();
    const response = await completeLogin(
      callback({ code: "c", state }, loginCookie),
      CONFIG,
      deps(tokenResponse({ expires_in: 86_400 })),
    );
    const cookie = setCookies(response).find((c) => c.startsWith(`${SESSION_COOKIE}=`))!;
    expect(cookie).toContain(`Max-Age=${MAX_SESSION_SECONDS}`);
  });

  it.each([
    ["state mismatch", (s: string) => ({ code: "c", state: s.slice(1) + "x" }), true, "failed"],
    ["missing code", (s: string) => ({ state: s }), true, "failed"],
    ["missing state", () => ({ code: "c" }), true, "failed"],
    ["no login cookie", (s: string) => ({ code: "c", state: s }), false, "failed"],
  ])("rejects %s without contacting Cognito", async (_, query, withCookie, expected) => {
    const { state, loginCookie } = await beginLogin();
    const d = deps();
    const response = await completeLogin(callback(query(state), withCookie ? loginCookie : undefined), CONFIG, d);
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=${expected}`);
    expect(d.fetchMock).not.toHaveBeenCalled();
    expect(cookieValue(response, SESSION_COOKIE)).toBeUndefined();
  });

  it("rejects an expired login transaction", async () => {
    const { state, loginCookie } = await beginLogin(NOW);
    const d = deps(tokenResponse(), NOW + (LOGIN_TTL_SECONDS + 1) * 1000);
    const response = await completeLogin(callback({ code: "c", state }, loginCookie), CONFIG, d);
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=expired`);
    expect(d.fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a session cookie presented as a login transaction", async () => {
    const { state, loginCookie } = await beginLogin();
    const signedIn = await completeLogin(callback({ code: "c", state }, loginCookie), CONFIG, deps());
    const sessionCookie = cookieValue(signedIn, SESSION_COOKIE)!;
    const d = deps();
    const response = await completeLogin(callback({ code: "c", state }, sessionCookie), CONFIG, d);
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
    expect(d.fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["access_denied", "cancelled"],
    ["server_error", "failed"],
  ])("maps provider error %s to a fixed outcome without echoing it", async (error, expected) => {
    const { state, loginCookie } = await beginLogin();
    const response = await completeLogin(
      callback({ error, error_description: "<script>alert(1)</script>", state }, loginCookie),
      CONFIG,
      deps(),
    );
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=${expected}`);
    expect(await response.text()).toBe("");
    // A state-validated error consumes the login transaction.
    expect(setCookies(response).find((c) => c.startsWith(`${LOGIN_COOKIE}=`))).toContain("Max-Age=0");
  });

  describe("forged callbacks cannot cancel an in-progress login", () => {
    const forgedStates: [string, (state: string) => Record<string, string>][] = [
      ["missing state", () => ({})],
      ["empty state", () => ({ state: "" })],
      ["invalid state", () => ({ state: "not a state value \u0000" })],
      ["mismatched state", (s) => ({ state: s.slice(0, -1) + (s.endsWith("A") ? "B" : "A") })],
      ["another login's state", () => ({ state: createState() })],
    ];

    it.each(forgedStates)(
      "an OAuth error callback with %s leaves the login cookie intact",
      async (_, stateParams) => {
        const { state, loginCookie } = await beginLogin();
        for (const error of ["access_denied", "server_error"]) {
          const forged = await completeLogin(
            callback({ error, ...stateParams(state) }, loginCookie),
            CONFIG,
            deps(),
          );
          expect(forged.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
          expect(setCookies(forged)).toEqual([]);
        }

        // The genuine callback still completes with the untouched cookie.
        const genuine = await completeLogin(callback({ code: "c", state }, loginCookie), CONFIG, deps());
        expect(genuine.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
        expect(cookieValue(genuine, SESSION_COOKIE)).toBeDefined();
      },
    );

    it.each(forgedStates)(
      "a code callback with %s leaves the login cookie intact",
      async (_, stateParams) => {
        const { state, loginCookie } = await beginLogin();
        const d = deps();
        const forged = await completeLogin(callback({ code: "forged", ...stateParams(state) }, loginCookie), CONFIG, d);
        expect(forged.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
        expect(setCookies(forged)).toEqual([]);
        expect(d.fetchMock).not.toHaveBeenCalled();
      },
    );

    it("an error callback without any login transaction sets no session and reports failure", async () => {
      const response = await completeLogin(callback({ error: "access_denied", state: "x" }), CONFIG, deps());
      expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
      expect(cookieValue(response, SESSION_COOKIE)).toBeUndefined();
    });

    it("an expired transaction is cleared even when the callback carries an error", async () => {
      const { state, loginCookie } = await beginLogin(NOW);
      const response = await completeLogin(
        callback({ error: "access_denied", state }, loginCookie),
        CONFIG,
        deps(tokenResponse(), NOW + (LOGIN_TTL_SECONDS + 1) * 1000),
      );
      expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=expired`);
      expect(setCookies(response).find((c) => c.startsWith(`${LOGIN_COOKIE}=`))).toContain("Max-Age=0");
    });
  });

  it.each([
    ["HTTP 400", tokenResponse({ error: "invalid_grant" }, 400)],
    ["network error", new Error("connect ECONNREFUSED")],
    ["non-JSON body", new Response("<html>", { status: 200 })],
    ["missing access token", tokenResponse({ access_token: undefined })],
    ["wrong token type", tokenResponse({ token_type: "mac" })],
    ["non-positive lifetime", tokenResponse({ expires_in: 0 })],
    ["oversized token", tokenResponse({ access_token: "x".repeat(5000) })],
  ])("fails closed on %s from the token endpoint", async (_, response) => {
    const { state, loginCookie } = await beginLogin();
    const result = await completeLogin(callback({ code: "c", state }, loginCookie), CONFIG, deps(response));
    expect(result.headers.get("location")).toBe(`${WEB_ORIGIN}/?auth=failed`);
    expect(cookieValue(result, SESSION_COOKIE)).toBeUndefined();
  });

  it("never redirects to a URL taken from the request", async () => {
    const { state, loginCookie } = await beginLogin();
    const response = await completeLogin(
      callback({ code: "c", state, redirect_uri: "https://evil.example", return_to: "https://evil.example" }, loginCookie),
      CONFIG,
      deps(),
    );
    expect(response.headers.get("location")).toBe(`${WEB_ORIGIN}/`);
  });
});

describe("parseSession", () => {
  it("rejects expired and malformed sessions", () => {
    expect(parseSession({ accessToken: "t", exp: 100 }, 100)).toBeNull();
    expect(parseSession({ accessToken: "t", exp: 101 }, 100)).toEqual({ accessToken: "t", exp: 101 });
    expect(parseSession({ exp: 101 }, 100)).toBeNull();
    expect(parseSession(null, 100)).toBeNull();
  });
});

describe("logout", () => {
  const post = (headers: Record<string, string>) =>
    new Request(`${WEB_ORIGIN}/auth/logout`, { method: "POST", headers });

  it("clears both cookies and ends the Cognito session", async () => {
    const response = await logout(post({ origin: WEB_ORIGIN }), CONFIG, deps());
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location")!);
    expect(location.origin + location.pathname).toBe(`${COGNITO_ORIGIN}/logout`);
    expect(Object.fromEntries(location.searchParams)).toEqual({
      client_id: CONFIG.clientId,
      logout_uri: `${WEB_ORIGIN}/`,
    });
    const cookies = setCookies(response);
    expect(cookies.find((c) => c.startsWith(`${SESSION_COOKIE}=;`))).toContain("Max-Age=0");
    expect(cookies.find((c) => c.startsWith(`${LOGIN_COOKIE}=;`))).toContain("Max-Age=0");
  });

  it("accepts Sec-Fetch-Site same-origin when no Origin header is sent", async () => {
    expect((await logout(post({ "sec-fetch-site": "same-origin" }), CONFIG, deps())).status).toBe(303);
  });

  it.each([
    [{ origin: "https://evil.example" }],
    [{ origin: "null" }],
    [{ "sec-fetch-site": "cross-site" }],
    [{}],
  ])("refuses cross-site or unverifiable requests: %o", async (headers) => {
    const response = await logout(post(headers), CONFIG, deps());
    expect(response.status).toBe(403);
    expect(setCookies(response)).toEqual([]);
  });
});
