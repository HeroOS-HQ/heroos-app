import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleBlueprintUpdate } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Company profile update from the settings form (lib/server/bff.ts). PATCH only. */
export async function PATCH(
  request: Request,
  context: RouteContext<"/bff/companies/[companyId]/blueprint">,
): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId } = await context.params;
  return handleBlueprintUpdate(request, result.config, companyId, { fetch, now: Date.now });
}
