import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleNotedSave } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Ask HeroOS: the employer saves what HeroOS noted to the conversation's Case (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/assistant/conversations/[conversationId]/noted">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, conversationId } = await context.params;
  return handleNotedSave(request, result.config, companyId, conversationId, { fetch, now: Date.now });
}
