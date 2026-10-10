import { connection } from "next/server";

import { notConfigured, startLogin } from "@/lib/server/auth-flow";
import { readAuthConfig } from "@/lib/server/config";

export async function GET(): Promise<Response> {
  // Request time only: with Cache Components a GET handler that reads no request
  // data would be prerendered, freezing one state/PKCE verifier for everyone.
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  return startLogin(result.config, { fetch, now: Date.now });
}
