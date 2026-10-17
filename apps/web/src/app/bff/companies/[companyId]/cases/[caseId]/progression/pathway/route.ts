import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handlePathwaySelect } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** The employer's pathway choice from the guided Case workspace (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/progression/pathway">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handlePathwaySelect(request, result.config, companyId, caseId, { fetch, now: Date.now });
}
