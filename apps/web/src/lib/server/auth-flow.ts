import "server-only";

import { type AuthConfig, callbackUrl, signedOutUrl } from "./config";
import { LOGIN_COOKIE, SESSION_COOKIE, expireCookie, readCookie, serializeCookie } from "./cookies";
import { codeChallenge, createCodeVerifier, createState, sameState } from "./pkce";
import { seal, unseal } from "./sealed";

/**
 * OAuth 2.0 Authorization Code + PKCE against Cognito managed login, run entirely
 * on the web server (backend-for-frontend). See docs/architecture/authentication.md §10.
 *
 * - The browser only ever holds sealed, HttpOnly cookies: never an access,
 *   ID or refresh token.
 * - Only the access token is kept. ID and refresh tokens from the token response
 *   are discarded, so a session ends when its access token expires.
 * - Redirect targets are fixed (never taken from the request): no open redirect.
 * - Failures redirect to `/?auth=<fixed code>`; provider error text is never echoed.
 */

export type Deps = { fetch: typeof fetch; now: () => number };

export const LOGIN_TTL_SECONDS = 600;
/** Upper bound for a session, whatever `expires_in` says. */
export const MAX_SESSION_SECONDS = 3600;
/** Browsers drop cookies over ~4096 bytes; refuse rather than half-set a session. */
export const MAX_SEALED_SESSION_LENGTH = 3800;
const TOKEN_TIMEOUT_MS = 10_000;

export type AuthOutcome = "failed" | "cancelled" | "expired";

type LoginTransaction = { state: string; verifier: string; exp: number };
export type Session = { accessToken: string; exp: number };

const seconds = (deps: Deps) => Math.floor(deps.now() / 1000);

function redirect(location: string, cookies: string[], status = 303): Response {
  const headers = new Headers({ Location: location, "Cache-Control": "no-store" });
  for (const cookie of cookies) headers.append("Set-Cookie", cookie);
  return new Response(null, { status, headers });
}

function outcome(config: AuthConfig, code: AuthOutcome, cookies: string[]): Response {
  return redirect(`${config.webOrigin}/?auth=${code}`, cookies);
}

/** GET /auth/login: new state + PKCE verifier in a sealed 10-minute cookie, then Cognito. */
export function startLogin(config: AuthConfig, deps: Deps): Response {
  const state = createState();
  const verifier = createCodeVerifier();
  const transaction: LoginTransaction = {
    state,
    verifier,
    exp: seconds(deps) + LOGIN_TTL_SECONDS,
  };
  const authorize = new URL("/oauth2/authorize", config.cognitoOrigin);
  authorize.search = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: callbackUrl(config),
    scope: "openid",
    state,
    code_challenge: codeChallenge(verifier),
    code_challenge_method: "S256",
  }).toString();
  return redirect(
    authorize.toString(),
    [serializeCookie(LOGIN_COOKIE, seal(transaction, config.sessionSecret, "login"), LOGIN_TTL_SECONDS)],
    302,
  );
}

function parseTransaction(value: unknown): LoginTransaction | null {
  if (typeof value !== "object" || value === null) return null;
  const { state, verifier, exp } = value as Record<string, unknown>;
  if (typeof state !== "string" || typeof verifier !== "string" || typeof exp !== "number") {
    return null;
  }
  return { state, verifier, exp };
}

/** GET /auth/callback: validate state, exchange the code server-side, set the session. */
export async function completeLogin(request: Request, config: AuthConfig, deps: Deps): Promise<Response> {
  const url = new URL(request.url);
  // The login transaction is single-use: cleared on every outcome.
  const cookies = [expireCookie(LOGIN_COOKIE)];
  const transaction = parseTransaction(
    unseal(readCookie(request.headers.get("cookie"), LOGIN_COOKIE), config.sessionSecret, "login"),
  );

  if (url.searchParams.has("error")) {
    const cancelled = url.searchParams.get("error") === "access_denied";
    return outcome(config, cancelled ? "cancelled" : "failed", cookies);
  }
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!transaction || !code || !state) return outcome(config, "failed", cookies);
  if (transaction.exp <= seconds(deps)) return outcome(config, "expired", cookies);
  if (!sameState(transaction.state, state)) return outcome(config, "failed", cookies);

  let accessToken: string;
  let expiresIn: number;
  try {
    const response = await deps.fetch(new URL("/oauth2/token", config.cognitoOrigin), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: config.clientId,
        code,
        redirect_uri: callbackUrl(config),
        code_verifier: transaction.verifier,
      }),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(TOKEN_TIMEOUT_MS),
    });
    if (!response.ok) return outcome(config, "failed", cookies);
    const body = (await response.json()) as Record<string, unknown>;
    if (
      typeof body.access_token !== "string" ||
      typeof body.token_type !== "string" ||
      body.token_type.toLowerCase() !== "bearer" ||
      typeof body.expires_in !== "number" ||
      !(body.expires_in > 0)
    ) {
      return outcome(config, "failed", cookies);
    }
    accessToken = body.access_token;
    expiresIn = Math.min(body.expires_in, MAX_SESSION_SECONDS);
  } catch {
    // Network error, timeout or malformed JSON. Nothing about it is returned.
    return outcome(config, "failed", cookies);
  }

  const session: Session = { accessToken, exp: seconds(deps) + expiresIn };
  const sealed = seal(session, config.sessionSecret, "session");
  if (sealed.length > MAX_SEALED_SESSION_LENGTH) return outcome(config, "failed", cookies);
  return redirect(`${config.webOrigin}/`, [...cookies, serializeCookie(SESSION_COOKIE, sealed, expiresIn)]);
}

export function parseSession(value: unknown, nowSeconds: number): Session | null {
  if (typeof value !== "object" || value === null) return null;
  const { accessToken, exp } = value as Record<string, unknown>;
  if (typeof accessToken !== "string" || typeof exp !== "number" || exp <= nowSeconds) return null;
  return { accessToken, exp };
}

/**
 * POST /auth/logout: same-origin only (blocks cross-site logout forcing), clears
 * both cookies, then ends the Cognito managed-login session.
 */
export function logout(request: Request, config: AuthConfig): Response {
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  const sameOrigin = origin !== null ? origin === config.webOrigin : fetchSite === "same-origin";
  if (!sameOrigin) {
    return new Response("Forbidden", { status: 403, headers: { "Cache-Control": "no-store" } });
  }
  const signOut = new URL("/logout", config.cognitoOrigin);
  signOut.search = new URLSearchParams({
    client_id: config.clientId,
    logout_uri: signedOutUrl(config),
  }).toString();
  return redirect(signOut.toString(), [expireCookie(SESSION_COOKIE), expireCookie(LOGIN_COOKIE)]);
}

export function notConfigured(): Response {
  return new Response("Sign-in is not configured.", {
    status: 503,
    headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
  });
}
