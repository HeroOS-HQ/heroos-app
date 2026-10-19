import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleDocumentsList } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** The Case's document templates and whether each can be previewed now (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/documents">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleDocumentsList(request, result.config, companyId, caseId, { fetch, now: Date.now });
}
