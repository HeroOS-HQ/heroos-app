import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleConversationMessages } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Ask HeroOS: older messages of one conversation (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/assistant/conversations/[conversationId]/messages">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, conversationId } = await context.params;
  return handleConversationMessages(request, result.config, companyId, conversationId, { fetch, now: Date.now });
}
