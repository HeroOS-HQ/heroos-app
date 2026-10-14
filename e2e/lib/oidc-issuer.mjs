// A local, controlled OpenID Provider for end-to-end tests (never deployed).
//
// It plays the part Auth0 plays in the demo: OIDC discovery, a JWKS, a hosted
// login page (/authorize), the token endpoint (Authorization Code + PKCE S256)
// and RP-initiated logout. It is deliberately strict, like a real provider:
// exact client and redirect-URI registration, S256 only, single-use codes that
// expire after 60 seconds, the requested audience must be the API's.
//
// The web app and the API are configured with this issuer exactly as they
// would be with Auth0; both run their production verification code. Access
// tokens are RFC 9068 JWTs signed with a key generated for this run only.
import { createHash, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:https";

import { accessTokenClaims, newSigningKey, signToken } from "./jwt.mjs";

const CODE_TTL_MS = 60_000;

const html = (body) => `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HeroOS E2E sign-in</title></head>
<body>${body}</body></html>`;

const escape = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function readBody(req, limit = 16 * 1024) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new Error("body too large");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export class TestIssuer {
  /**
   * @param {{ port: number, tls: { cert: string, key: string }, audience: string,
   *           clients: Record<string, { redirectUris: string[], postLogoutRedirectUris: string[] }>,
   *           tokenLifetimeSeconds?: number }} options
   */
  constructor({ port, tls, audience, clients, tokenLifetimeSeconds = 600 }) {
    this.port = port;
    // Trailing slash, as Auth0 issuers have: compared verbatim by web and API.
    this.issuer = `https://localhost:${port}/`;
    this.origin = `https://localhost:${port}`;
    this.audience = audience;
    this.clients = clients;
    this.tokenLifetimeSeconds = tokenLifetimeSeconds;
    this.key = newSigningKey();
    this.tls = tls;
    this.requests = new Map();
    this.codes = new Map();
    /** Every protocol event, for assertions (never contains tokens). */
    this.events = [];
    // Emulation of the staging Auth0 setup, opt-in per subject: a Post Login
    // Action denies unverified e-mail with the reason `email_not_verified`, and
    // Auth0 remembers the authentication in its own session cookie, so a later
    // /authorize skips the form and runs the Action again. Subjects never marked
    // keep the plain behaviour (a form on every /authorize, no provider session).
    this.emailUnverified = new Set();
    this.remembered = new Set();
    this.sessions = new Map();
  }

  /** The subject signs up with an unverified e-mail address (see the constructor). */
  requireVerifiedEmail(subject) {
    this.emailUnverified.add(subject);
    this.remembered.add(subject);
  }

  /** The subject opened the verification link. */
  verifyEmail(subject) {
    this.emailUnverified.delete(subject);
  }

  start() {
    this.server = createServer(
      { cert: readFileSync(this.tls.cert), key: readFileSync(this.tls.key) },
      (req, res) => this.#handle(req, res).catch(() => this.#send(res, 500, { error: "server_error" })),
    );
    return new Promise((resolve) => this.server.listen(this.port, "127.0.0.1", resolve));
  }

  stop() {
    return new Promise((resolve) => (this.server ? this.server.close(() => resolve()) : resolve()));
  }

  /** A valid access token for `subject`, as /token would issue it (API-level tests). */
  accessToken(subject, { clientId = Object.keys(this.clients)[0], lifetimeSeconds, overrides } = {}) {
    const claims = accessTokenClaims({
      issuer: this.issuer,
      audience: this.audience,
      clientId,
      subject,
      lifetimeSeconds: lifetimeSeconds ?? this.tokenLifetimeSeconds,
      overrides,
    });
    return signToken(claims, this.key);
  }

  metadata() {
    return {
      issuer: this.issuer,
      authorization_endpoint: `${this.origin}/authorize`,
      token_endpoint: `${this.origin}/oauth/token`,
      jwks_uri: `${this.origin}/.well-known/jwks.json`,
      end_session_endpoint: `${this.origin}/oidc/logout`,
      response_types_supported: ["code"],
      code_challenge_methods_supported: ["S256"],
      grant_types_supported: ["authorization_code"],
      subject_types_supported: ["public"],
      id_token_signing_alg_values_supported: ["RS256"],
      token_endpoint_auth_methods_supported: ["none"],
    };
  }

  #send(res, status, body, headers = {}) {
    const json = typeof body !== "string";
    res.writeHead(status, {
      "Content-Type": json ? "application/json" : "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      ...headers,
    });
    res.end(json ? JSON.stringify(body) : body);
  }

  #redirect(res, location, headers = {}) {
    res.writeHead(302, { Location: location, "Cache-Control": "no-store", ...headers });
    res.end();
  }

  #sessionId(req) {
    const match = /(?:^|;\s*)e2e_idp_session=([A-Za-z0-9_-]+)/.exec(req.headers.cookie ?? "");
    return match && this.sessions.has(match[1]) ? match[1] : null;
  }

  /** After authentication: the emulated Post Login Action, then the code. */
  #complete(request, subject, res, headers = {}) {
    const back = new URL(request.redirect_uri);
    back.searchParams.set("state", request.state);
    if (this.emailUnverified.has(subject)) {
      back.searchParams.set("error", "access_denied");
      back.searchParams.set("error_description", "email_not_verified");
      this.events.push({ type: "post_login_denied", reason: "email_not_verified" });
      return this.#redirect(res, back.toString(), headers);
    }
    const code = randomBytes(24).toString("base64url");
    this.codes.set(code, {
      subject,
      clientId: request.client_id,
      redirectUri: request.redirect_uri,
      challenge: request.code_challenge,
      expires: Date.now() + CODE_TTL_MS,
    });
    back.searchParams.set("code", code);
    this.events.push({ type: "code_issued", clientId: request.client_id });
    return this.#redirect(res, back.toString(), headers);
  }

  async #handle(req, res) {
    const url = new URL(req.url, this.origin);
    if (req.method === "GET" && url.pathname === "/.well-known/openid-configuration") {
      return this.#send(res, 200, this.metadata());
    }
    if (req.method === "GET" && url.pathname === "/.well-known/jwks.json") {
      return this.#send(res, 200, { keys: [this.key.jwk] });
    }
    if (req.method === "GET" && url.pathname === "/authorize") return this.#authorize(url, req, res);
    if (req.method === "POST" && url.pathname === "/authorize/decision") return this.#decision(req, res);
    if (req.method === "POST" && url.pathname === "/oauth/token") return this.#token(req, res);
    if (req.method === "GET" && url.pathname === "/oidc/logout") return this.#logout(url, req, res);
    return this.#send(res, 404, { error: "not_found" });
  }

  #authorize(url, req, res) {
    const p = Object.fromEntries(url.searchParams);
    const client = this.clients[p.client_id];
    // Never redirect to an unregistered URI: answer on this page instead.
    if (!client || !client.redirectUris.includes(p.redirect_uri)) {
      this.events.push({ type: "authorize_rejected", reason: "client_or_redirect_uri" });
      return this.#send(res, 400, html("<h1>Invalid client or redirect URI</h1>"));
    }
    const invalid =
      p.response_type !== "code" ? "unsupported_response_type"
      : p.code_challenge_method !== "S256" || !/^[A-Za-z0-9_-]{43}$/.test(p.code_challenge ?? "") ? "invalid_request"
      : !p.state ? "invalid_request"
      : p.audience !== this.audience ? "invalid_request"
      : null;
    if (invalid) {
      this.events.push({ type: "authorize_rejected", reason: invalid });
      const back = new URL(p.redirect_uri);
      back.searchParams.set("error", invalid);
      if (p.state) back.searchParams.set("state", p.state);
      return this.#redirect(res, back.toString());
    }
    const remembered = this.#sessionId(req);
    if (remembered) {
      // Like Auth0 with a live session: no form, straight to the Post Login step.
      this.events.push({ type: "authorize", clientId: p.client_id, screenHint: p.screen_hint ?? null, extraParams: [], session: true });
      return this.#complete(p, this.sessions.get(remembered), res);
    }
    const id = randomBytes(16).toString("hex");
    this.requests.set(id, { ...p, created: Date.now() });
    this.events.push({
      type: "authorize",
      clientId: p.client_id,
      screenHint: p.screen_hint ?? null,
      extraParams: Object.keys(p).filter((k) =>
        !["response_type", "client_id", "redirect_uri", "scope", "state", "code_challenge",
          "code_challenge_method", "audience", "screen_hint"].includes(k)),
    });
    const heading = p.screen_hint === "signup" ? "Create your account" : "Sign in";
    return this.#send(res, 200, html(`
      <main>
        <h1 id="heading">${heading}</h1>
        <p>Local HeroOS end-to-end test provider. Synthetic identities only.</p>
        <form method="post" action="/authorize/decision">
          <input type="hidden" name="request" value="${escape(id)}">
          <label for="subject">Subject</label>
          <input id="subject" name="subject" autocomplete="off">
          <button id="continue" name="decision" value="allow" type="submit">Continue</button>
          <button id="cancel" name="decision" value="deny" type="submit">Cancel</button>
        </form>
      </main>`));
  }

  async #decision(req, res) {
    const form = new URLSearchParams(await readBody(req));
    const request = this.requests.get(form.get("request") ?? "");
    if (!request) return this.#send(res, 400, html("<h1>Unknown or used request</h1>"));
    this.requests.delete(form.get("request"));
    const back = new URL(request.redirect_uri);
    back.searchParams.set("state", request.state);
    if (form.get("decision") !== "allow") {
      back.searchParams.set("error", "access_denied");
      this.events.push({ type: "authorize_denied" });
      return this.#redirect(res, back.toString());
    }
    const subject = form.get("subject") ?? "";
    if (!subject) return this.#send(res, 400, html("<h1>Subject required</h1>"));
    const headers = {};
    if (this.remembered.has(subject)) {
      // The provider session exists once the user authenticated, even when the
      // Post Login step then denies the login.
      const sid = randomBytes(16).toString("base64url");
      this.sessions.set(sid, subject);
      headers["Set-Cookie"] = `e2e_idp_session=${sid}; Path=/; Secure; HttpOnly; SameSite=Lax`;
    }
    return this.#complete(request, subject, res, headers);
  }

  async #token(req, res) {
    const form = new URLSearchParams(await readBody(req));
    const fail = (reason) => {
      this.events.push({ type: "token_rejected", reason });
      return this.#send(res, 400, { error: "invalid_grant" });
    };
    if (form.get("grant_type") !== "authorization_code") return fail("grant_type");
    const code = this.codes.get(form.get("code") ?? "");
    // Single use, even when the rest of the request is wrong.
    this.codes.delete(form.get("code") ?? "");
    if (!code || code.expires < Date.now()) return fail("code");
    if (form.get("client_id") !== code.clientId) return fail("client_id");
    if (form.get("redirect_uri") !== code.redirectUri) return fail("redirect_uri");
    const verifier = form.get("code_verifier") ?? "";
    const challenge = createHash("sha256").update(verifier).digest("base64url");
    if (challenge !== code.challenge) return fail("pkce");
    this.events.push({ type: "token_issued", clientId: code.clientId });
    return this.#send(res, 200, {
      access_token: this.accessToken(code.subject, { clientId: code.clientId }),
      token_type: "Bearer",
      expires_in: this.tokenLifetimeSeconds,
      scope: "openid",
    });
  }

  #logout(url, req, res) {
    const client = this.clients[url.searchParams.get("client_id") ?? ""];
    const target = url.searchParams.get("post_logout_redirect_uri");
    if (!client || !client.postLogoutRedirectUris.includes(target)) {
      this.events.push({ type: "logout_rejected" });
      return this.#send(res, 400, html("<h1>Invalid logout request</h1>"));
    }
    const sid = this.#sessionId(req);
    if (sid) this.sessions.delete(sid);
    this.events.push({ type: "logout", endedSession: sid !== null });
    return this.#redirect(res, target, sid ? { "Set-Cookie": "e2e_idp_session=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0" } : {});
  }
}
