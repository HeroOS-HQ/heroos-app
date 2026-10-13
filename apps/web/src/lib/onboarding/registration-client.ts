import { type FieldName, type RegistrationPayload } from "./model";

/**
 * Browser side of founder registration: one POST to this web app's BFF
 * (`/bff/registrations`), never to the HeroOS API and never with a token.
 * Anything other than a well-formed success is a failure; a lost or garbled
 * response is "uncertain" (the workspace may or may not exist), never success.
 */

export type RegistrationFailure =
  /** 401: the session ended. */
  | "session_expired"
  /** 403: the API refused this account (suspended, revoked, or similar). */
  | "refused"
  /** 404: self-service registration is not switched on in this environment. */
  | "disabled"
  /** 422: a field was refused. */
  | "invalid"
  /** No usable answer (network, timeout, 5xx): the outcome is unknown. */
  | "uncertain"
  /** Anything else (should not happen from this app's own pages). */
  | "generic";

export type RegistrationOutcome =
  | { kind: "success"; outcome: "created" | "existing"; companyId: string }
  | { kind: "failure"; reason: RegistrationFailure; fields: FieldName[] };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FIELD_NAMES = new Set<FieldName>([
  "companyName",
  "legalName",
  "industry",
  "employeeCount",
  "licensingLocation",
  "licensingAuthority",
]);

const failure = (reason: RegistrationFailure, fields: FieldName[] = []): RegistrationOutcome => ({
  kind: "failure",
  reason,
  fields,
});

/** Interpret a BFF response. Pure, so every status is testable. */
export function interpretRegistrationResponse(status: number, body: unknown): RegistrationOutcome {
  const record = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  if (status === 201 || status === 200) {
    const outcome = record.outcome;
    const expected = status === 201 ? "created" : "existing";
    if (outcome === expected && typeof record.companyId === "string" && UUID.test(record.companyId)) {
      return { kind: "success", outcome: expected, companyId: record.companyId };
    }
    return failure("uncertain");
  }
  if (status === 401) return failure("session_expired");
  if (status === 403) return failure(record.error === "refused" ? "refused" : "generic");
  if (status === 404) return failure("disabled");
  if (status === 422) {
    const fields = Array.isArray(record.fields)
      ? record.fields.filter((field): field is FieldName => FIELD_NAMES.has(field as FieldName))
      : [];
    return failure("invalid", fields);
  }
  if (status >= 500 || status === 0) return failure("uncertain");
  return failure("generic");
}

export const REGISTRATION_TIMEOUT_MS = 45_000;

/** POST the validated payload to the BFF. Never throws. */
export async function submitRegistration(
  payload: RegistrationPayload,
  fetcher: typeof fetch = fetch,
): Promise<RegistrationOutcome> {
  let response: Response;
  try {
    response = await fetcher("/bff/registrations", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      signal: AbortSignal.timeout(REGISTRATION_TIMEOUT_MS),
    });
  } catch {
    return failure("uncertain");
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return interpretRegistrationResponse(response.status, body);
}

/** Where to go after a successful registration (ids from the API only). */
export function readyPath(outcome: "created" | "existing", companyId: string): string {
  return `/workspaces/${companyId}/ready?outcome=${outcome}`;
}
