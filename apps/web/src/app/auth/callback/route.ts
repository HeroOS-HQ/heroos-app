import { connection } from "next/server";

import { completeLogin, notConfigured } from "@/lib/server/auth-flow";
import { readAuthConfig } from "@/lib/server/config";

export async function GET(request: Request): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  return completeLogin(request, result.config, { fetch, now: Date.now });
}
