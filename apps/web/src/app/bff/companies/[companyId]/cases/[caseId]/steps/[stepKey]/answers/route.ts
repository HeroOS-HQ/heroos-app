import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleAnswersSave } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Saved answers from the guided Case workspace (lib/server/bff.ts). PUT only. */
export async function PUT(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/steps/[stepKey]/answers">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId, stepKey } = await context.params;
  return handleAnswersSave(request, result.config, companyId, caseId, stepKey, { fetch, now: Date.now });
}
