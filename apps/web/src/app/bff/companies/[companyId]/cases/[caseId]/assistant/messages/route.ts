import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleAssistantMessage } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

// Room for the API's wait on the model provider (45 s) on any Vercel plan.
export const maxDuration = 60;

/** One message to Hannah, her reply; nothing is stored (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/assistant/messages">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleAssistantMessage(request, result.config, companyId, caseId, {
    fetch,
    now: Date.now,
  });
}
