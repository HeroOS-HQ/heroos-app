import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleConversationDetail } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Ask HeroOS: one conversation, its status and latest messages (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/assistant/conversations/[conversationId]">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, conversationId } = await context.params;
  return handleConversationDetail(request, result.config, companyId, conversationId, { fetch, now: Date.now });
}
