import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleRegistration } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Founder registration from the onboarding form (lib/server/bff.ts). POST only. */
export async function POST(request: Request): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  return handleRegistration(request, result.config, { fetch, now: Date.now });
}
