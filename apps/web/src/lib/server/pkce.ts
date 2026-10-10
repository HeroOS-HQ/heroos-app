import "server-only";

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";

/** PKCE (RFC 7636, S256) and OAuth `state` values. */

/** 32 random bytes -> 43-character base64url code verifier. */
export function createCodeVerifier(): string {
  return randomBytes(32).toString("base64url");
}

export function codeChallenge(verifier: string): string {
  return createHash("sha256").update(verifier, "ascii").digest("base64url");
}

export function createState(): string {
  return randomBytes(32).toString("base64url");
}

/** Constant-time comparison of two state values. */
export function sameState(expected: string, received: string): boolean {
  const a = Buffer.from(expected);
  const b = Buffer.from(received);
  return a.length === b.length && timingSafeEqual(a, b);
}
