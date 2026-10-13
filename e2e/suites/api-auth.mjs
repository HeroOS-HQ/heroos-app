// Phase E (API): access-token validation through the real API process and its
// production OIDC verification (discovery + JWKS from the test provider).
//
// The baseline: a valid token for an identity HeroOS does not know gets 403
// from /me/companies (authenticated, not provisioned). Every forgery must get
// 401 instead: authentication fails before any authorization question.
import { randomUUID } from "node:crypto";

import { accessTokenClaims, newSigningKey, publicKeyPem, signToken } from "../lib/jwt.mjs";

export async function run(ctx) {
  const { check, issuer, apiFetch } = ctx;
  const subject = ctx.subject("auth-probe");
  const claims = (overrides = {}) =>
    accessTokenClaims({ issuer: issuer.issuer, audience: ctx.AUDIENCE, clientId: ctx.CLIENT_ID, subject, overrides });
  const status = async (token) => (await apiFetch("/me/companies", { token })).status;

  const valid = ctx.token(subject);
  check("AUTH-1", "a valid token for an unknown identity is authenticated but not authorized (403)", (await status(valid)) === 403);

  const missing = await apiFetch("/me/companies");
  check("AUTH-2", "no token: 401 with WWW-Authenticate: Bearer", missing.status === 401 && missing.headers.get("www-authenticate") === "Bearer");
  for (const path of ["/company-registrations", `/companies/${randomUUID()}`, `/companies/${randomUUID()}/blueprint`]) {
    const method = path === "/company-registrations" ? "POST" : "GET";
    const res = await apiFetch(path, { method, body: method === "POST" ? { company_name: "X" } : undefined });
    check("AUTH-3", `no token on ${method} ${path.replace(/[0-9a-f-]{36}/, "{id}")}: 401`, res.status === 401, res.status);
  }

  const otherKey = newSigningKey(issuer.key.kid);
  const cases = [
    ["AUTH-4", "signed by another key with the same kid", signToken(claims(), otherKey)],
    ["AUTH-5", "unsigned (alg none)", signToken(claims(), null, { alg: "none" })],
    ["AUTH-6", "HS256 with the issuer's public key as the secret (algorithm confusion)",
      signToken(claims(), null, { alg: "HS256", kid: issuer.key.kid, hmacSecret: publicKeyPem(issuer.key) })],
    ["AUTH-7", "wrong issuer", signToken(claims({ iss: "https://evil.example/" }), issuer.key)],
    ["AUTH-8", "issuer without the trailing slash (compared verbatim)", signToken(claims({ iss: issuer.issuer.replace(/\/$/, "") }), issuer.key)],
    ["AUTH-9", "wrong audience", signToken(claims({ aud: "https://another-api.example" }), issuer.key)],
    ["AUTH-10", "ID-token shape: audience is the client ID", signToken(claims({ aud: ctx.CLIENT_ID }), issuer.key)],
    ["AUTH-11", "expired", signToken(claims({ exp: Math.floor(Date.now() / 1000) - 120, iat: Math.floor(Date.now() / 1000) - 900 }), issuer.key)],
    ["AUTH-12", "not yet valid (nbf in the future)", signToken(claims({ nbf: Math.floor(Date.now() / 1000) + 3600 }), issuer.key)],
    ["AUTH-13", "wrong token type (typ JWT, not at+jwt)", signToken(claims(), issuer.key, { typ: "JWT" })],
    ["AUTH-14", "carries ID-token claims (nonce)", signToken(claims({ nonce: "n" }), issuer.key)],
    ["AUTH-15", "issued to a client that is not allow-listed", signToken(claims({ client_id: ctx.OTHER_CLIENT_ID }), issuer.key)],
    ["AUTH-16", "client_id and azp disagree", signToken(claims({ azp: ctx.OTHER_CLIENT_ID }), issuer.key)],
    ["AUTH-17", "missing jti (RFC 9068)", signToken(claims({ jti: undefined }), issuer.key)],
    ["AUTH-18", "missing client_id (RFC 9068)", signToken(claims({ client_id: undefined }), issuer.key)],
    ["AUTH-19", "empty subject", signToken(claims({ sub: "" }), issuer.key)],
    ["AUTH-20", "unknown kid", signToken(claims(), newSigningKey("unknown-kid"))],
  ];
  for (const [id, name, token] of cases) {
    // Rejected tokens must not reach the logs either.
    ctx.issuedTokens.push(token);
    const res = await apiFetch("/me/companies", { token });
    const signature = token.split(".")[2];
    check(id, `${name}: 401`, res.status === 401 && !(signature && res.text.includes(signature)), `status ${res.status}`);
  }

  const [header, payload, signature] = valid.split(".");
  const tampered = JSON.parse(Buffer.from(payload, "base64url").toString());
  tampered.sub = ctx.subject("someone-else");
  const tamperedToken = `${header}.${Buffer.from(JSON.stringify(tampered)).toString("base64url")}.${signature}`;
  check("AUTH-21", "a payload changed after signing: 401", (await status(tamperedToken)) === 401);

  const generic = await apiFetch("/me/companies", { token: cases[0][2] });
  check("AUTH-22", "authentication failures are generic (fixed body, nothing echoed)",
    generic.json?.detail === "Not authenticated" && Object.keys(generic.json ?? {}).length === 1);
  check("AUTH-23", "API responses are no-store", (generic.headers.get("cache-control") ?? "").includes("no-store"));
  const cors = await apiFetch("/me/companies", { token: valid, headers: { Origin: "https://evil.example" } });
  check("AUTH-24", "the API grants no CORS access to a foreign origin", cors.headers.get("access-control-allow-origin") === null);
  const docs = await apiFetch("/openapi.json");
  check("AUTH-25", "staging publishes no OpenAPI schema or docs", docs.status === 404);
}
