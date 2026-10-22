import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleAskChat } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

// Room for the API's wait on the model provider (45 s) on any Vercel plan.
export const maxDuration = 60;

/** Ask HeroOS's staging chat-only demo: one message, one reply; nothing is stored (lib/server/bff.ts). POST only. */
export async function POST(request: Request, context: RouteContext<"/bff/companies/[companyId]/assistant/chat">): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId } = await context.params;
  return handleAskChat(request, result.config, companyId, { fetch, now: Date.now });
}
