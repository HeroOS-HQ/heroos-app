import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleCaseWorkflow } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** The Case's view as the API has it now, for Ask HeroOS's inline Case steps (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/workflow">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleCaseWorkflow(request, result.config, companyId, caseId, { fetch, now: Date.now });
}
