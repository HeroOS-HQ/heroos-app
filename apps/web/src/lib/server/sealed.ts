import "server-only";

import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from "node:crypto";

/**
 * Authenticated encryption for cookie values (AES-256-GCM).
 *
 * A separate key is derived per purpose with HKDF, and the purpose is also bound
 * as additional authenticated data, so a login-transaction cookie can never be
 * replayed as a session cookie (or the reverse). Any tampering, wrong key or wrong
 * purpose makes `unseal` return null. Format: `v1.<iv>.<ciphertext>.<tag>` (base64url).
 */

export type SealPurpose = "session" | "login";

const VERSION = "v1";
const IV_BYTES = 12;

function key(secret: Buffer, purpose: SealPurpose): Buffer {
  return Buffer.from(hkdfSync("sha256", secret, Buffer.alloc(0), `heroos-web/${purpose}`, 32));
}

export function seal(payload: unknown, secret: Buffer, purpose: SealPurpose): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", key(secret, purpose), iv);
  cipher.setAAD(Buffer.from(purpose));
  const body = Buffer.concat([cipher.update(JSON.stringify(payload), "utf8"), cipher.final()]);
  return [VERSION, iv, body, cipher.getAuthTag()]
    .map((part) => (typeof part === "string" ? part : part.toString("base64url")))
    .join(".");
}

export function unseal(
  value: string | undefined,
  secret: Buffer,
  purpose: SealPurpose,
): unknown {
  if (!value) return null;
  const parts = value.split(".");
  if (parts.length !== 4 || parts[0] !== VERSION) return null;
  try {
    const [iv, body, tag] = parts.slice(1).map((part) => Buffer.from(part, "base64url"));
    if (iv.length !== IV_BYTES || tag.length !== 16) return null;
    const decipher = createDecipheriv("aes-256-gcm", key(secret, purpose), iv);
    decipher.setAAD(Buffer.from(purpose));
    decipher.setAuthTag(tag);
    const plain = Buffer.concat([decipher.update(body), decipher.final()]);
    return JSON.parse(plain.toString("utf8"));
  } catch {
    return null;
  }
}
