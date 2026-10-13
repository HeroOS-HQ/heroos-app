// JSON Web Tokens for the local test issuer (node:crypto only).
//
// `mint` produces RFC 9068 access tokens exactly as a real OpenID Provider
// would for the HeroOS API audience. Its options exist to build the invalid
// tokens the authentication tests need (wrong issuer, audience, type, key,
// algorithm, expiry, ...). These keys and tokens exist only inside one test
// run; nothing here is used by application code.
import { createHmac, createPublicKey, generateKeyPairSync, randomBytes, randomUUID, sign } from "node:crypto";

const b64url = (value) => Buffer.from(value).toString("base64url");

export function newSigningKey(kid = `e2e-${randomBytes(4).toString("hex")}`) {
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const jwk = { ...publicKey.export({ format: "jwk" }), kid, alg: "RS256", use: "sig" };
  return { kid, privateKey, publicKey, jwk };
}

function encode(header, payload, signer) {
  const signingInput = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(payload))}`;
  return `${signingInput}.${signer(signingInput)}`;
}

/**
 * Signs `claims` with `key` (RS256 unless `alg` says otherwise).
 * `alg: "none"` produces an unsigned token; `alg: "HS256"` signs with
 * `hmacSecret` (used to prove the API refuses algorithm confusion).
 */
export function signToken(claims, key, { alg = "RS256", typ = "at+jwt", kid = key?.kid, hmacSecret } = {}) {
  const header = { alg, typ, ...(kid ? { kid } : {}) };
  if (alg === "none") return encode(header, claims, () => "");
  if (alg === "HS256") {
    return encode(header, claims, (input) => createHmac("sha256", hmacSecret).update(input).digest("base64url"));
  }
  return encode(header, claims, (input) => sign("sha256", Buffer.from(input), key.privateKey).toString("base64url"));
}

/** Standard access-token claims for `subject`; `overrides` replace or (with undefined) remove claims. */
export function accessTokenClaims({ issuer, audience, clientId, subject, lifetimeSeconds = 600, overrides = {} }) {
  const now = Math.floor(Date.now() / 1000);
  const claims = {
    iss: issuer,
    sub: subject,
    aud: audience,
    client_id: clientId,
    jti: randomUUID(),
    iat: now,
    exp: now + lifetimeSeconds,
    scope: "openid",
  };
  for (const [name, value] of Object.entries(overrides)) {
    if (value === undefined) delete claims[name];
    else claims[name] = value;
  }
  return claims;
}

/** PEM of the public key (for the algorithm-confusion test: public key used as an HMAC secret). */
export function publicKeyPem(key) {
  return createPublicKey(key.privateKey).export({ format: "pem", type: "spki" });
}
