import "server-only";

import type { AuthConfig } from "./config";

/**
 * Server-side HeroOS API client. The access token is attached here, on the web
 * server, and never reaches the browser. Responses are mapped to fixed outcomes;
 * API error bodies are never rendered.
 */

export type Company = { id: string; name: string };
export type CaseSummary = {
  id: string;
  title: string;
  caseType: string;
  createdAt: string;
};

export type ApiFailure = "unauthenticated" | "forbidden" | "not_found" | "unavailable";
export type ApiResult<T> = { ok: true; data: T } | { ok: false; failure: ApiFailure };

type Fetch = typeof fetch;
const API_TIMEOUT_MS = 10_000;

function failureFor(status: number): ApiFailure {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  return "unavailable";
}

async function apiGet<T>(
  path: string,
  accessToken: string,
  config: AuthConfig,
  fetcher: Fetch,
  parse: (body: unknown) => T | null,
): Promise<ApiResult<T>> {
  try {
    const response = await fetcher(`${config.apiBaseUrl}${path}`, {
      headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!response.ok) return { ok: false, failure: failureFor(response.status) };
    const data = parse(await response.json());
    return data === null ? { ok: false, failure: "unavailable" } : { ok: true, data };
  } catch {
    return { ok: false, failure: "unavailable" };
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

export function parseCompany(body: unknown): Company | null {
  if (!isRecord(body) || typeof body.id !== "string" || typeof body.name !== "string") return null;
  return { id: body.id, name: body.name };
}

export function parseCases(body: unknown): CaseSummary[] | null {
  if (!Array.isArray(body)) return null;
  const cases: CaseSummary[] = [];
  for (const item of body) {
    if (
      !isRecord(item) ||
      typeof item.id !== "string" ||
      typeof item.title !== "string" ||
      typeof item.case_type !== "string" ||
      typeof item.created_at !== "string"
    ) {
      return null;
    }
    cases.push({ id: item.id, title: item.title, caseType: item.case_type, createdAt: item.created_at });
  }
  return cases;
}

export type CompanyOverview = {
  /** Only Companies whose API request succeeded (Membership + RLS decided by the API). */
  companies: Company[];
  /** The Company shown: the single authorized one, or the validated choice. Otherwise null. */
  selected: { company: Company; cases: CaseSummary[] } | null;
};

/**
 * Demo-only Company discovery. Each configured candidate is requested through the
 * protected API; a candidate is listed only when the API authorizes it. A
 * requested Company outside that authorized list is ignored, never fetched.
 */
export async function getCompanyOverview(
  accessToken: string,
  config: AuthConfig,
  requestedCompanyId: string | null = null,
  fetcher: Fetch = fetch,
): Promise<ApiResult<CompanyOverview>> {
  const lookups = await Promise.all(
    config.demoCompanyIds.map((id) =>
      apiGet(`/companies/${encodeURIComponent(id)}`, accessToken, config, fetcher, parseCompany),
    ),
  );
  // Fail closed: an expired token or an unreachable API never degrades to a partial list.
  for (const failure of ["unauthenticated", "unavailable"] as const) {
    if (lookups.some((lookup) => !lookup.ok && lookup.failure === failure)) {
      return { ok: false, failure };
    }
  }
  const companies: Company[] = [];
  config.demoCompanyIds.forEach((id, index) => {
    const lookup = lookups[index];
    // The API echoes the requested id; anything else is not trusted.
    if (lookup.ok && lookup.data.id === id) companies.push(lookup.data);
  });
  if (companies.length === 0) {
    const notFound = lookups.every((lookup) => !lookup.ok && lookup.failure === "not_found");
    return { ok: false, failure: notFound ? "not_found" : "forbidden" };
  }

  const selectedCompany =
    companies.length === 1 ? companies[0] : (companies.find((c) => c.id === requestedCompanyId) ?? null);
  if (selectedCompany === null) return { ok: true, data: { companies, selected: null } };

  const cases = await apiGet(
    `/companies/${encodeURIComponent(selectedCompany.id)}/cases`,
    accessToken,
    config,
    fetcher,
    parseCases,
  );
  if (!cases.ok) return { ok: false, failure: cases.failure };
  return { ok: true, data: { companies, selected: { company: selectedCompany, cases: cases.data } } };
}
