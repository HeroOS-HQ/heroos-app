import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleGatewayMessage } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

// Room for the API's founder turn (up to four model requests in 40 s) on any Vercel plan.
export const maxDuration = 60;

/** Ask HeroOS: one founder message and HeroOS's reply, stored together (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/assistant/messages">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId } = await context.params;
  return handleGatewayMessage(request, result.config, companyId, { fetch, now: Date.now });
}
