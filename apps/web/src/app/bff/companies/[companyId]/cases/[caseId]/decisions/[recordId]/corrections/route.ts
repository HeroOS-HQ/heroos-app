import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleDecisionCorrection } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** A correction or clarification of a decision record (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/decisions/[recordId]/corrections">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId, recordId } = await context.params;
  return handleDecisionCorrection(request, result.config, companyId, caseId, recordId, { fetch, now: Date.now });
}
