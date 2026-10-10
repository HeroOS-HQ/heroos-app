import "server-only";

import { cookies } from "next/headers";
import { connection } from "next/server";

import { type Session, parseSession } from "./auth-flow";
import type { AuthConfig } from "./config";
import { SESSION_COOKIE } from "./cookies";
import { unseal } from "./sealed";

/** The current browser session, or null if absent, tampered with or expired. */
export async function readSession(config: AuthConfig): Promise<Session | null> {
  const value = (await cookies()).get(SESSION_COOKIE)?.value;
  // Expiry is checked against the request time, never a prerender-time clock.
  await connection();
  return parseSession(unseal(value, config.sessionSecret, "session"), Math.floor(Date.now() / 1000));
}
