// Phases E (web) and F: the sign-in flow, the session cookie, logout and the
// two BFF routes, exercised over HTTP against the real web server, which calls
// the real API. Browser-only checks (storage, history, UI) are in browser.mjs.
import { counts, newFounder, quote, sameCounts } from "./common.mjs";

const setCookies = (res) => res.headers.getSetCookie?.() ?? [];
const cookieValue = (res, name) => {
  const line = setCookies(res).find((c) => c.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).split(";")[0] : null;
};

/** The provider's half of a sign-in, without a browser: returns the callback URL and the login cookie. */
async function providerRoundTrip(ctx, subject, { intent = "login", query = "" } = {}) {
  const start = await fetch(`${ctx.webOrigin}/auth/${intent}${query}`, { redirect: "manual" });
  const authorize = new URL(start.headers.get("location"));
  const loginCookie = cookieValue(start, "__Host-heroos-login");
  const page = await (await fetch(authorize)).text();
  const request = /name="request" value="([0-9a-f]+)"/.exec(page)?.[1];
  const decision = await fetch(`${ctx.issuer.origin}/authorize/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ request, subject, decision: "allow" }),
    redirect: "manual",
  });
  return { start, authorize, loginCookie, callback: new URL(decision.headers.get("location")) };
}

async function callback(ctx, callbackUrl, loginCookie) {
  return fetch(callbackUrl, { headers: loginCookie ? { Cookie: `__Host-heroos-login=${loginCookie}` } : {}, redirect: "manual" });
}

export async function run(ctx) {
  const { check, webOrigin, issuer, fixtures } = ctx;

  // --- sign-in flow (Phase E, web) -------------------------------------------------
  const login = await fetch(`${webOrigin}/auth/login`, { redirect: "manual" });
  const authorize = new URL(login.headers.get("location"));
  const loginSetCookie = setCookies(login).find((c) => c.startsWith("__Host-heroos-login="));
  check("WEB-1", "/auth/login redirects to the provider with code + PKCE S256, state and the API audience",
    login.status === 302 && authorize.origin === issuer.origin && authorize.searchParams.get("response_type") === "code" &&
    authorize.searchParams.get("code_challenge_method") === "S256" && authorize.searchParams.get("state")?.length >= 32 &&
    authorize.searchParams.get("audience") === ctx.AUDIENCE && !authorize.searchParams.has("screen_hint"), authorize.toString().slice(0, 200));
  check("WEB-2", "the login transaction cookie is __Host-, HttpOnly, Secure, SameSite=Lax, Path=/",
    /HttpOnly/.test(loginSetCookie) && /Secure/.test(loginSetCookie) && /SameSite=Lax/.test(loginSetCookie) && /Path=\//.test(loginSetCookie));
  const signup = await fetch(`${webOrigin}/auth/signup`, { redirect: "manual" });
  check("WEB-3", "/auth/signup asks the provider for its sign-up screen (screen_hint=signup)", new URL(signup.headers.get("location")).searchParams.get("screen_hint") === "signup");

  const injected = await fetch(`${webOrigin}/auth/login?returnTo=https://evil.example/&redirect_uri=https://evil.example/cb&next=//evil.example`, { redirect: "manual" });
  const injectedAuthorize = new URL(injected.headers.get("location"));
  check("WEB-4", "redirect parameters on /auth/login are ignored: the callback is always the web origin's",
    injectedAuthorize.searchParams.get("redirect_uri") === `${webOrigin}/auth/callback` && !injectedAuthorize.toString().includes("evil"));

  const founderSubject = ctx.subject("web-login");
  const good = await providerRoundTrip(ctx, founderSubject, { query: "?returnTo=https://evil.example/" });
  const forgedState = new URL(good.callback);
  forgedState.searchParams.set("state", "x".repeat(43));
  const badState = await callback(ctx, forgedState, good.loginCookie);
  check("WEB-5", "a callback with a wrong state fails (?auth=failed), sets no session, and never contacts the token endpoint",
    badState.headers.get("location") === `${webOrigin}/?auth=failed` && !cookieValue(badState, "__Host-heroos-session") &&
    !issuer.events.some((e) => e.type === "token_rejected"));
  const noCookie = await callback(ctx, good.callback, null);
  check("WEB-6", "a callback without the login transaction cookie fails (?auth=failed)", noCookie.headers.get("location") === `${webOrigin}/?auth=failed`);

  const success = await callback(ctx, good.callback, good.loginCookie);
  const sessionLine = setCookies(success).find((c) => c.startsWith("__Host-heroos-session="));
  check("WEB-7", "the genuine callback signs in: 303 to a fixed landing page with a __Host- HttpOnly Secure SameSite=Lax session",
    success.status === 303 && success.headers.get("location") === `${webOrigin}/` && /HttpOnly/.test(sessionLine ?? "") &&
    /Secure/.test(sessionLine ?? "") && /SameSite=Lax/.test(sessionLine ?? ""), success.headers.get("location"));
  check("WEB-8", "auth responses are no-store and the session cookie is opaque (no token inside)",
    (success.headers.get("cache-control") ?? "").includes("no-store") && !(sessionLine ?? "").includes("eyJ"));
  const replay = await callback(ctx, good.callback, good.loginCookie);
  check("WEB-9", "replaying the same callback (code reuse) fails: the code is single-use", replay.headers.get("location") === `${webOrigin}/?auth=failed`);

  const expiredLogin = await providerRoundTrip(ctx, founderSubject);
  const state = expiredLogin.callback.searchParams.get("state");
  const expiredCookie = ctx.seal({ state, verifier: "v".repeat(43), exp: Math.floor(Date.now() / 1000) - 5, intent: "login" }, "login");
  const expired = await callback(ctx, expiredLogin.callback, expiredCookie);
  check("WEB-10", "an expired login transaction fails (?auth=expired)", expired.headers.get("location") === `${webOrigin}/?auth=expired`);

  const pkce = await providerRoundTrip(ctx, founderSubject);
  const swapped = ctx.seal({ state: pkce.callback.searchParams.get("state"), verifier: "w".repeat(43), exp: Math.floor(Date.now() / 1000) + 300, intent: "login" }, "login");
  const rejectedBefore = issuer.events.filter((e) => e.type === "token_rejected" && e.reason === "pkce").length;
  const pkceResult = await callback(ctx, pkce.callback, swapped);
  check("WEB-11", "a PKCE verifier that does not match the challenge is refused by the provider; sign-in fails",
    pkceResult.headers.get("location") === `${webOrigin}/?auth=failed` &&
    issuer.events.filter((e) => e.type === "token_rejected" && e.reason === "pkce").length === rejectedBefore + 1);
  const cancelled = await providerRoundTrip(ctx, founderSubject);
  const cancelUrl = new URL(`${webOrigin}/auth/callback`);
  cancelUrl.searchParams.set("error", "access_denied");
  cancelUrl.searchParams.set("state", cancelled.callback.searchParams.get("state"));
  const cancel = await callback(ctx, cancelUrl, cancelled.loginCookie);
  check("WEB-12", "a cancelled sign-in at the provider ends on ?auth=cancelled", cancel.headers.get("location") === `${webOrigin}/?auth=cancelled`);

  // --- logout ---------------------------------------------------------------------
  const session = cookieValue(success, "__Host-heroos-session");
  ctx.issuedSessions.push(session);
  const crossLogout = await ctx.webFetch("/auth/logout", { method: "POST", session, headers: { Origin: "https://evil.example" } });
  check("WEB-13", "a cross-site logout is refused (403)", crossLogout.status === 403);
  const getLogout = await ctx.webFetch("/auth/logout", { session });
  check("WEB-14", "GET /auth/logout is not allowed (405)", getLogout.status === 405);
  const logoutRes = await fetch(`${webOrigin}/auth/logout`, { method: "POST", headers: { Cookie: `__Host-heroos-session=${session}`, Origin: webOrigin }, redirect: "manual" });
  const endSession = new URL(logoutRes.headers.get("location"));
  check("WEB-15", "logout clears both cookies and ends the provider session (RP-initiated logout to the registered URL)",
    logoutRes.status === 303 && endSession.origin === issuer.origin && endSession.searchParams.get("post_logout_redirect_uri") === `${webOrigin}/` &&
    setCookies(logoutRes).filter((c) => /Max-Age=0/.test(c)).length === 2);

  // --- session expiry -------------------------------------------------------------------
  const founder = await newFounder(ctx, "bff-founder", { company_name: "[SYNTHETIC E2E] BFF Co.", blueprint: { licensing: { location: "difc" } } });
  const expiredSession = ctx.seal({ accessToken: founder.token, exp: Math.floor(Date.now() / 1000) - 1 }, "session");
  const signedOut = await ctx.webFetch("/workspaces", { session: expiredSession });
  check("WEB-16", "an expired session cookie is treated as signed out", signedOut.text.includes("Please sign in") && !signedOut.text.includes("BFF Co."));
  const staleToken = ctx.token(founder.subject, { lifetimeSeconds: -60 });
  const staleSession = ctx.session(staleToken);
  const ended = await ctx.webFetch("/workspaces", { session: staleSession });
  check("WEB-17", "a session whose access token the API rejects shows \"Your session has ended\", no data", ended.text.includes("Your session has ended") && !ended.text.includes("BFF Co."));

  const live = ctx.session(founder.token);
  for (const path of ["/workspaces", `/workspaces/${founder.companyId}`, `/workspaces/${founder.companyId}/settings`, "/onboarding"]) {
    const res = await ctx.webFetch(path, { session: live });
    check("WEB-18", `signed-in page ${path.replace(/[0-9a-f-]{36}/, "{id}")} is private, no-store and contains no token`,
      (res.headers.get("cache-control") ?? "").includes("no-store") && (res.headers.get("cache-control") ?? "").includes("private") && !res.text.includes(founder.token), res.headers.get("cache-control"));
  }

  const headers = (await ctx.webFetch(`/workspaces/${founder.companyId}`, { session: live })).headers;
  const csp = headers.get("content-security-policy") ?? "";
  check("WEB-19", "signed-in pages carry the security headers: nonce CSP (no unsafe-inline/unsafe-eval), frame-ancestors none, HSTS, nosniff, no-referrer, DENY",
    /script-src 'self' 'nonce-[^']+' 'strict-dynamic'/.test(csp) && !/unsafe-inline|unsafe-eval|unsafe-hashes/.test(csp) && /frame-ancestors 'none'/.test(csp) &&
    /connect-src 'self'/.test(csp) && headers.get("strict-transport-security")?.startsWith("max-age=") && headers.get("x-content-type-options") === "nosniff" &&
    headers.get("referrer-policy") === "no-referrer" && headers.get("x-frame-options") === "DENY", csp);

  // --- BFF guards (Phase F) ------------------------------------------------------------------
  const unprovisioned = ctx.subject("bff-new-founder");
  const newSession = ctx.session(ctx.token(unprovisioned));
  const body = JSON.stringify({ company_name: "[SYNTHETIC E2E] Via BFF Co.", blueprint: { licensing: { location: "not_sure" } } });
  const bff = (path, { method = "POST", session: s = newSession, headers = {}, payload = body } = {}) =>
    ctx.webFetch(path, { method, session: s, body: payload, headers: { "Content-Type": "application/json", Origin: webOrigin, ...headers } });
  const isSanitized = (res) => res.json && Object.keys(res.json).every((k) => ["error", "fields", "outcome", "companyId", "blueprint"].includes(k));
  const responses = [];
  const track = (res) => {
    responses.push(res);
    return res;
  };

  const before = await counts(ctx);
  const crossOrigin = track(await bff("/bff/registrations", { headers: { Origin: "https://evil.example" } }));
  check("BFF-1", "cross-origin POST: 403 forbidden_origin", crossOrigin.status === 403 && crossOrigin.json?.error === "forbidden_origin");
  const nullCross = track(await bff("/bff/registrations", { headers: { Origin: "null", "Sec-Fetch-Site": "cross-site" } }));
  check("BFF-2", "Origin: null with Sec-Fetch-Site: cross-site: 403", nullCross.status === 403 && nullCross.json?.error === "forbidden_origin");
  const noOrigin = track(await ctx.webFetch("/bff/registrations", { method: "POST", session: newSession, body, headers: { "Content-Type": "application/json" } }));
  check("BFF-3", "no Origin and no Fetch Metadata: 403", noOrigin.status === 403);
  const form = track(await bff("/bff/registrations", { headers: { "Content-Type": "application/x-www-form-urlencoded" }, payload: "company_name=x" }));
  const plain = track(await bff("/bff/registrations", { headers: { "Content-Type": "text/plain" } }));
  check("BFF-4", "form and text/plain bodies (cross-site \"simple\" requests): 415", form.status === 415 && plain.status === 415);
  const big = track(await bff("/bff/registrations", { payload: JSON.stringify({ company_name: "x".repeat(17 * 1024) }) }));
  check("BFF-5", "a body over 16 KiB: 413", big.status === 413 && big.json?.error === "payload_too_large");
  const noSession = track(await bff("/bff/registrations", { session: null }));
  check("BFF-6", "no session: 401 session_expired", noSession.status === 401 && noSession.json?.error === "session_expired");
  const expiredBff = track(await bff("/bff/registrations", { session: ctx.seal({ accessToken: "x", exp: Math.floor(Date.now() / 1000) - 1 }, "session") }));
  const tampered = track(await bff("/bff/registrations", { session: `${newSession.slice(0, -4)}AAAA` }));
  check("BFF-7", "an expired or tampered session: 401", expiredBff.status === 401 && tampered.status === 401);
  const malformed = track(await bff("/bff/registrations", { payload: "{not json" }));
  check("BFF-8", "malformed JSON: 400 invalid_request", malformed.status === 400 && malformed.json?.error === "invalid_request");
  const unknown = track(await bff("/bff/registrations", { payload: JSON.stringify({ company_name: "X", blueprint: { licensing: { location: "difc" } }, role: "company_admin" }) }));
  const nested = track(await bff("/bff/registrations", { payload: JSON.stringify({ company_name: "X", blueprint: { licensing: { location: "difc" }, employment_jurisdiction: "difc" } }) }));
  check("BFF-9", "unknown fields (top-level or in the Blueprint): 422, never forwarded", unknown.status === 422 && nested.status === 422);
  check("BFF-10", "every refused request created nothing", sameCounts(await counts(ctx), before));

  const created = track(await bff("/bff/registrations"));
  check("BFF-11", "a valid same-origin request registers through the BFF: 201 {outcome, companyId} only", created.status === 201 && created.json?.outcome === "created" && Object.keys(created.json).length === 2);
  const nullSame = track(await bff("/bff/registrations", { headers: { Origin: "null", "Sec-Fetch-Site": "same-origin" } }));
  check("BFF-12", "Origin: null with Sec-Fetch-Site: same-origin is accepted (no-referrer browsers); the retry is 200 existing", nullSame.status === 200 && nullSame.json?.companyId === created.json?.companyId);

  // PATCH: administrator, other tenant, malformed id, member.
  const founderSession = ctx.session(founder.token);
  const patchBody = JSON.stringify({ industry: "Consulting" });
  const okPatch = track(await bff(`/bff/companies/${founder.companyId}/blueprint`, { method: "PATCH", session: founderSession, payload: patchBody }));
  check("BFF-13", "an administrator's PATCH through the BFF: 200 with the API's Blueprint", okPatch.status === 200 && okPatch.json?.blueprint?.industry === "Consulting");
  const cross = track(await bff(`/bff/companies/${ctx.alpha?.companyId ?? created.json.companyId}/blueprint`, { method: "PATCH", session: founderSession, payload: patchBody }));
  check("BFF-14", "PATCH of another Company through the BFF: 403 refused (decided by the API)", cross.status === 403 && cross.json?.error === "refused");
  const badId = track(await bff("/bff/companies/not-a-uuid/blueprint", { method: "PATCH", session: founderSession, payload: patchBody }));
  check("BFF-15", "a malformed Company id: 403 refused, never sent to the API", badId.status === 403);
  const patchUnknown = track(await bff(`/bff/companies/${founder.companyId}/blueprint`, { method: "PATCH", session: founderSession, payload: JSON.stringify({ role: "company_admin" }) }));
  check("BFF-16", "PATCH with a field outside the allowed set: 422", patchUnknown.status === 422);
  if (ctx.alphaMember) {
    const memberSession = ctx.session(ctx.token(ctx.alphaMember.subject));
    const memberPatch = track(await bff(`/bff/companies/${ctx.alpha.companyId}/blueprint`, { method: "PATCH", session: memberSession, payload: patchBody }));
    check("BFF-17", "a revoked member's PATCH through the BFF: 403", memberPatch.status === 403);
  }

  // Backend failures through the real stack.
  const staleBff = track(await bff(`/bff/companies/${founder.companyId}/blueprint`, { method: "PATCH", session: staleSession, payload: patchBody }));
  check("BFF-18", "backend 401 (token rejected by the API): 401 session_expired", staleBff.status === 401 && staleBff.json?.error === "session_expired");
  await ctx.api.stop();
  await ctx.api.start({ selfRegistration: false });
  const disabled = track(await bff("/bff/registrations", { session: ctx.session(ctx.token(ctx.subject("bff-disabled"))) }));
  check("BFF-19", "backend 404 (registration disabled): 404 registration_unavailable", disabled.status === 404 && disabled.json?.error === "registration_unavailable");
  await ctx.api.stop();
  const down = track(await bff("/bff/registrations", { session: ctx.session(ctx.token(ctx.subject("bff-down"))) }));
  check("BFF-20", "API unreachable: 503 unavailable", down.status === 503 && down.json?.error === "unavailable");
  await ctx.api.start({ selfRegistration: true });
  ctx.api.freeze();
  const started = Date.now();
  const hung = track(await bff("/bff/registrations", { session: ctx.session(ctx.token(ctx.subject("bff-timeout"))) }));
  const waited = Date.now() - started;
  ctx.api.resume();
  check("BFF-21", "API not answering: the BFF gives up (503 unavailable) instead of hanging", hung.status === 503 && waited < 40_000, `${waited} ms`);
  ctx.report.notRun("BFF-22", "backend 422 and 5xx mapping through the real stack", "the BFF validates exactly as the API does, so a 422 cannot reach the API from a valid BFF request; both mappings are covered by apps/web/src/lib/server/bff.test.ts");
  const hungCompany = await fixtures.ownerValue(`SELECT count(*) FROM user_identities WHERE subject = ${quote(ctx.subject("bff-timeout"))}`);
  check("BFF-23", "after a timeout the outcome is unknown to the client, not invented (record if the API finished it)", hungCompany === "0" || hungCompany === "1", `registrations for the frozen request: ${hungCompany}`);

  check("BFF-24", "every BFF response is no-store", responses.every((r) => (r.headers.get("cache-control") ?? "").includes("no-store")));
  check("BFF-25", "every BFF error body is a fixed code (no API text, no stack, no token)", responses.every((r) => isSanitized(r) && !/eyJ|Traceback|detail/.test(r.text)));
  const get = await ctx.webFetch("/bff/registrations", { session: newSession });
  check("BFF-26", "GET on a BFF route is not allowed (405)", get.status === 405);
}
