import { connection } from "next/server";

import { logout, notConfigured } from "@/lib/server/auth-flow";
import { readAuthConfig } from "@/lib/server/config";

// POST only: a GET (e.g. an <img> on another site) cannot sign the user out.
export async function POST(request: Request): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  return logout(request, result.config);
}
