import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleCaseCreate } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** New workflow Case from the New case form (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/workflows/[workflowKey]/cases">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, workflowKey } = await context.params;
  return handleCaseCreate(request, result.config, companyId, workflowKey, { fetch, now: Date.now });
}
