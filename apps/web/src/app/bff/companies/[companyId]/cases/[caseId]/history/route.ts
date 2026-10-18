import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleHistoryPage } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** An older page of the unified case history (lib/server/bff.ts). GET only. */
export async function GET(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/cases/[caseId]/history">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId, caseId } = await context.params;
  return handleHistoryPage(request, result.config, companyId, caseId, { fetch, now: Date.now });
}
