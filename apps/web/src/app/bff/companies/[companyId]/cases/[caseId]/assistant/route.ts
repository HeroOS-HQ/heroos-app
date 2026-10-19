import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleAssistantStatus } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Whether the signed-in administrator can talk to Hannah in this Case (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/assistant">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleAssistantStatus(request, result.config, companyId, caseId, {
    fetch,
    now: Date.now,
  });
}
