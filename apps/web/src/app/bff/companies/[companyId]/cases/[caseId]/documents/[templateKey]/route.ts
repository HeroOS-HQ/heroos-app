import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleDocumentForm } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** An available template's form (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/documents/[templateKey]">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId, templateKey } = await context.params;
  return handleDocumentForm(request, result.config, companyId, caseId, templateKey, { fetch, now: Date.now });
}
