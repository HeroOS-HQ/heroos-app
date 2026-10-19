import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleDocumentPreview } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/**
 * A preview of a template filled with what the administrator typed
 * (lib/server/bff.ts). POST only, so personal details never travel in a URL;
 * nothing is stored.
 */
export async function POST(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/documents/[templateKey]/preview">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId, templateKey } = await context.params;
  return handleDocumentPreview(request, result.config, companyId, caseId, templateKey, { fetch, now: Date.now });
}
