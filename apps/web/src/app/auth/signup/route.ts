import { connection } from "next/server";

import { notConfigured, startLogin } from "@/lib/server/auth-flow";
import { readAuthConfig } from "@/lib/server/config";

/**
 * "Get started": the identity provider's hosted sign-up (Auth0 Universal
 * Signup), then HeroOS company onboarding. Same Authorization Code + PKCE flow
 * as /auth/login; the only difference is a fixed sign-up intent. Nothing here
 * reads a redirect target or provider parameter from the request.
 */
export async function GET(): Promise<Response> {
  // Request time only, like /auth/login: never a prerendered state/verifier.
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  return startLogin(result.config, { fetch, now: Date.now }, "signup");
}
