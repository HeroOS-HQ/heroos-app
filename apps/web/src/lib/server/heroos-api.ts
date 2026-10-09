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

export type CompanyOverview = { company: Company; cases: CaseSummary[] };

/** The configured demo Company and its cases; the API decides whether the user may see them. */
export async function getCompanyOverview(
  accessToken: string,
  config: AuthConfig,
  fetcher: Fetch = fetch,
): Promise<ApiResult<CompanyOverview>> {
  const base = `/companies/${encodeURIComponent(config.demoCompanyId)}`;
  const [company, cases] = await Promise.all([
    apiGet(base, accessToken, config, fetcher, parseCompany),
    apiGet(`${base}/cases`, accessToken, config, fetcher, parseCases),
  ]);
  for (const failure of ["unauthenticated", "forbidden", "not_found", "unavailable"] as const) {
    if ((!company.ok && company.failure === failure) || (!cases.ok && cases.failure === failure)) {
      return { ok: false, failure };
    }
  }
  if (!company.ok || !cases.ok) return { ok: false, failure: "unavailable" };
  return { ok: true, data: { company: company.data, cases: cases.data } };
}
