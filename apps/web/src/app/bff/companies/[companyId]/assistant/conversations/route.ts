import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleConversationList } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Ask HeroOS: the Company's conversations, most recently active first (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/assistant/conversations">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId } = await context.params;
  return handleConversationList(request, result.config, companyId, { fetch, now: Date.now });
}
