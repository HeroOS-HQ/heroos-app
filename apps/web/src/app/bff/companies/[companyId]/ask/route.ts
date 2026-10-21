import { connection } from "next/server";

import { notConfigured } from "@/lib/server/auth-flow";
import { handleAskStart } from "@/lib/server/bff";
import { readAuthConfig } from "@/lib/server/config";

/** Ask HeroOS: the founder's question opens a case (lib/server/bff.ts, lib/ask/model.ts). POST only. */
export async function POST(request: Request, context: RouteContext<"/bff/companies/[companyId]/ask">): Promise<Response> {
  await connection();
  const result = readAuthConfig();
  if (!result.ok) return notConfigured();
  const { companyId } = await context.params;
  return handleAskStart(request, result.config, companyId, { fetch, now: Date.now });
}
