import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleDecisionRecord } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** A new employer decision record from the guided Case workspace (lib/server/bff.ts). POST only. */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/decisions">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleDecisionRecord(request, result.config, companyId, caseId, { fetch, now: Date.now });
}
