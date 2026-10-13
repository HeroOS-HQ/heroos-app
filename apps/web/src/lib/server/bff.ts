import "server-only";

import { type FieldName, parseBlueprintPatch, parseRegistrationRequest } from "@/lib/onboarding/model";

import { isSameOriginRequest, sessionFromRequest } from "./auth-flow";
import type { AuthConfig } from "./config";
import { type ApiFailure, registerCompany, updateBlueprint, UUID } from "./heroos-api";

/**
 * Backend-for-frontend mutations (M1-10D). The browser posts JSON to these
 * same-origin endpoints; the web server checks the request, attaches the
 * session's access token and calls the HeroOS API. The browser never holds a
 * token and never calls the API.
 *
 * Every request must:
 * 1. come from this web app's own pages (`Origin`, or `Sec-Fetch-Site` when the
 *    browser sends `Origin: null`): CSRF;
 * 2. be `application/json` (a cross-site HTML form cannot send it without a
 *    CORS preflight, which this app never grants), at most 16 KiB;
 * 3. carry a valid session.
 *
 * The body is re-validated and rebuilt field by field (unknown keys refused)
 * before it reaches the API. Responses carry fixed codes only: never an API
 * or provider error text.
 */

export type BffDeps = { fetch: typeof fetch; now: () => number };

/** Error codes the browser maps to fixed copy. */
export type BffError =
  | "forbidden_origin"
  | "unsupported_media_type"
  | "payload_too_large"
  | "invalid_request"
  | "session_expired"
  | "invalid"
  | "refused"
  | "registration_unavailable"
  | "not_found"
  | "unavailable";

export const MAX_BODY_BYTES = 16 * 1024;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

const error = (status: number, code: BffError, fields?: FieldName[]) =>
  json(status, fields ? { error: code, fields } : { error: code });

type Guarded = { ok: true; accessToken: string; body: unknown } | { ok: false; response: Response };

async function guard(request: Request, config: AuthConfig, deps: BffDeps): Promise<Guarded> {
  if (!isSameOriginRequest(request, config)) return { ok: false, response: error(403, "forbidden_origin") };
  const type = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (type !== "application/json") return { ok: false, response: error(415, "unsupported_media_type") };
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) return { ok: false, response: error(413, "payload_too_large") };

  const session = sessionFromRequest(request, config, Math.floor(deps.now() / 1000));
  if (session === null) return { ok: false, response: error(401, "session_expired") };

  let text: string;
  try {
    text = await request.text();
  } catch {
    return { ok: false, response: error(400, "invalid_request") };
  }
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
    return { ok: false, response: error(413, "payload_too_large") };
  }
  try {
    return { ok: true, accessToken: session.accessToken, body: JSON.parse(text) as unknown };
  } catch {
    return { ok: false, response: error(400, "invalid_request") };
  }
}

function apiFailure(failure: ApiFailure, fields: FieldName[] | undefined, refusal: BffError): Response {
  switch (failure) {
    case "unauthenticated":
      return error(401, "session_expired");
    case "forbidden":
      return error(403, refusal);
    case "invalid":
      return error(422, "invalid", fields ?? []);
    case "not_found":
      return error(404, refusal === "refused" ? "registration_unavailable" : "not_found");
    default:
      return error(503, "unavailable");
  }
}

/**
 * POST /bff/registrations → `POST /company-registrations`.
 *
 * 201 `{outcome: "created", companyId}`; 200 `{outcome: "existing", companyId}`
 * (this person registered before: the submitted details were NOT applied).
 * The API decides eligibility; nothing here infers it.
 */
export async function handleRegistration(request: Request, config: AuthConfig, deps: BffDeps): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  const parsed = parseRegistrationRequest(guarded.body);
  if (!parsed.ok) return error(422, "invalid", parsed.fields);

  const result = await registerCompany(guarded.accessToken, config, parsed.value, deps.fetch);
  if (!result.ok) return apiFailure(result.failure, result.fields, "refused");
  const { outcome, companyId } = result.data;
  return json(outcome === "created" ? 201 : 200, { outcome, companyId });
}

/**
 * PATCH /bff/companies/{id}/blueprint → `PATCH /companies/{id}/blueprint`.
 * Only administrators succeed (the API enforces it in the write transaction).
 */
export async function handleBlueprintUpdate(
  request: Request,
  config: AuthConfig,
  companyId: string,
  deps: BffDeps,
): Promise<Response> {
  const guarded = await guard(request, config, deps);
  if (!guarded.ok) return guarded.response;
  // Never sent to the API unless it is a well-formed id; any other value looks
  // like a Company the user cannot reach.
  if (!UUID.test(companyId)) return error(403, "refused");
  const parsed = parseBlueprintPatch(guarded.body);
  if (!parsed.ok) return error(422, "invalid", parsed.fields);

  const result = await updateBlueprint(guarded.accessToken, config, companyId, parsed.value, deps.fetch);
  if (!result.ok) return apiFailure(result.failure, result.fields, "refused");
  return json(200, { blueprint: result.data });
}
