import "server-only";

import type { Readiness } from "@/lib/onboarding/copy";
import {
  type BlueprintPatch,
  type FieldName,
  fieldsFromApiDetail,
  isLicensingLocation,
  type LicensingLocation,
  type RegistrationPayload,
} from "@/lib/onboarding/model";

import {
  type CaseSummary as WorkflowCaseSummary,
  FACT_KEY,
  KEY,
  parseCaseSummaries,
  parseCaseSummary,
  parseWorkflowView,
  type WorkflowView,
} from "@/lib/workflows/model";
import { ENTRY_ID, parseTimelinePage, type TimelinePage } from "@/lib/workflows/decisions";
import {
  CHOICE_KEY,
  type DocumentsList,
  FIELD_KEY,
  fromApiDocumentsList,
  fromApiPreview,
  fromApiTemplateForm,
  type Preview,
  TEMPLATE_KEY,
  type TemplateForm,
} from "@/lib/documents/model";
import type { PreviewPayload } from "@/lib/documents/requests";
import type { CorrectionPayload, DecisionPayload } from "@/lib/workflows/requests";

import type { AuthConfig } from "./config";

/**
 * Server-side HeroOS API client (backend-for-frontend). The access token is
 * attached here, on the web server, and never reaches the browser. Every
 * response is shape-checked; API error bodies are never passed on (only the
 * field names of a 422 are kept, mapped to known form fields).
 */

export type Role = "member" | "company_admin";
export type Company = { id: string; name: string };
export type CaseSummary = { id: string; title: string; caseType: string; createdAt: string };

/** A Company the signed-in user may open. `role` is null only on the legacy demo path. */
export type Workspace = { companyId: string; name: string; membershipId: string | null; role: Role | null };

export type Membership = { companyId: string; membershipId: string; role: Role; canUpdateBlueprint: boolean };

export type Blueprint = {
  companyId: string;
  legalName: string | null;
  industry: string | null;
  employeeCount: number | null;
  licensing: { location: LicensingLocation | null; authority: string | null };
  jurisdiction: {
    readiness: Readiness;
    reason: string;
    employmentJurisdiction: string | null;
    confirmedAt: string | null;
    guidanceAllowed: boolean;
  };
  updatedAt: string | null;
};

export type Registration = { outcome: "created" | "existing"; companyId: string; membershipId: string };

export type ApiFailure = "unauthenticated" | "forbidden" | "not_found" | "conflict" | "invalid" | "unavailable";
export type ApiResult<T> =
  | { ok: true; data: T }
  /**
   * `answerKeys`: the workflow questions a 422 named; `decisionFields`: the
   * decision-record fields it named; `documentFields`: the template fields
   * and choices it named (names only, never values).
   */
  | {
      ok: false;
      failure: ApiFailure;
      fields?: FieldName[];
      answerKeys?: string[];
      decisionFields?: string[];
      documentFields?: string[];
    };

type Fetch = typeof fetch;
const READ_TIMEOUT_MS = 10_000;
// Writes wait longer (a cold API can be slow to start). A timeout leaves the
// outcome unknown; registration is idempotent, so retrying is safe.
const WRITE_TIMEOUT_MS = 20_000;

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function failureFor(status: number): ApiFailure {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "invalid";
  return "unavailable";
}

type Call = { method?: "GET" | "POST" | "PATCH" | "PUT"; body?: unknown };

/** Question keys named by a 422 (`loc: ["body", "answers", key]`). */
export function answerKeysFromApiDetail(detail: unknown): string[] {
  if (!Array.isArray(detail)) return [];
  const keys = detail.flatMap((error) => {
    const loc = typeof error === "object" && error !== null ? (error as { loc?: unknown }).loc : null;
    return Array.isArray(loc) && loc[0] === "body" && loc[1] === "answers" && typeof loc[2] === "string" && FACT_KEY.test(loc[2])
      ? [loc[2]]
      : [];
  });
  return [...new Set(keys)];
}

/** Decision-record fields a 422 named (`loc: ["body", field, ...]`), M2-04. */
export const DECISION_FIELD_NAMES = [
  "category",
  "summary",
  "explanation",
  "occurred_on",
  "decision_maker",
  "decision_maker_role",
  "evidence_status",
  "evidence",
  "relation",
  "change_reason",
] as const;

export function decisionFieldsFromApiDetail(detail: unknown): string[] {
  if (!Array.isArray(detail)) return [];
  const fields = detail.flatMap((error) => {
    const loc = typeof error === "object" && error !== null ? (error as { loc?: unknown }).loc : null;
    return Array.isArray(loc) && loc[0] === "body" && (DECISION_FIELD_NAMES as readonly unknown[]).includes(loc[1])
      ? [loc[1] as string]
      : [];
  });
  return [...new Set(fields)];
}

/** Template fields and choices a preview 422 named (`loc: ["body", "values" | "choices", key]`), M2-04C. */
export function documentFieldsFromApiDetail(detail: unknown): string[] {
  if (!Array.isArray(detail)) return [];
  const fields = detail.flatMap((error) => {
    const loc = typeof error === "object" && error !== null ? (error as { loc?: unknown }).loc : null;
    if (!Array.isArray(loc) || loc[0] !== "body" || typeof loc[2] !== "string") return [];
    if (loc[1] === "values" && FIELD_KEY.test(loc[2])) return [loc[2]];
    if (loc[1] === "choices" && CHOICE_KEY.test(loc[2])) return [loc[2]];
    return [];
  });
  return [...new Set(fields)];
}

async function apiCall<T>(
  config: AuthConfig,
  accessToken: string,
  fetcher: Fetch,
  path: string,
  parse: (body: unknown) => T | null,
  call: Call = {},
): Promise<ApiResult<T>> {
  const write = call.body !== undefined;
  try {
    const response = await fetcher(`${config.apiBaseUrl}${path}`, {
      method: call.method ?? "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json",
        ...(write ? { "Content-Type": "application/json" } : {}),
      },
      body: write ? JSON.stringify(call.body) : undefined,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(write ? WRITE_TIMEOUT_MS : READ_TIMEOUT_MS),
    });
    if (!response.ok) {
      const failure = failureFor(response.status);
      if (failure !== "invalid") return { ok: false, failure };
      let detail: unknown = null;
      try {
        detail = ((await response.json()) as { detail?: unknown }).detail;
      } catch {
        // No usable body: the fields stay unknown.
      }
      const answerKeys = answerKeysFromApiDetail(detail);
      const decisionFields = decisionFieldsFromApiDetail(detail);
      const documentFields = documentFieldsFromApiDetail(detail);
      return {
        ok: false,
        failure,
        fields: fieldsFromApiDetail(detail),
        ...(answerKeys.length > 0 ? { answerKeys } : {}),
        ...(decisionFields.length > 0 ? { decisionFields } : {}),
        ...(documentFields.length > 0 ? { documentFields } : {}),
      };
    }
    const data = parse(await response.json());
    return data === null ? { ok: false, failure: "unavailable" } : { ok: true, data };
  } catch {
    return { ok: false, failure: "unavailable" };
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isId = (value: unknown): value is string => typeof value === "string" && UUID.test(value);
const isRole = (value: unknown): value is Role => value === "member" || value === "company_admin";
const optionalText = (value: unknown): value is string | null => value === null || typeof value === "string";

export function parseCompany(body: unknown): Company | null {
  if (!isRecord(body) || !isId(body.id) || typeof body.name !== "string") return null;
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

export function parseWorkspaces(body: unknown): Workspace[] | null {
  if (!Array.isArray(body)) return null;
  const workspaces: Workspace[] = [];
  for (const item of body) {
    if (
      !isRecord(item) ||
      !isId(item.company_id) ||
      typeof item.name !== "string" ||
      !isId(item.membership_id) ||
      !isRole(item.role)
    ) {
      return null;
    }
    workspaces.push({ companyId: item.company_id, name: item.name, membershipId: item.membership_id, role: item.role });
  }
  return workspaces;
}

export function parseMembership(body: unknown): Membership | null {
  if (
    !isRecord(body) ||
    !isId(body.company_id) ||
    !isId(body.membership_id) ||
    !isRole(body.role) ||
    typeof body.can_update_blueprint !== "boolean"
  ) {
    return null;
  }
  return {
    companyId: body.company_id,
    membershipId: body.membership_id,
    role: body.role,
    // Only an administrator can update, whatever else a response says.
    canUpdateBlueprint: body.role === "company_admin" && body.can_update_blueprint,
  };
}

const READINESS = new Set(["supported_confirmed", "unconfirmed", "unsupported"]);
const JURISDICTIONS = new Set(["uae_federal", "difc", "adgm", "other"]);

export function parseBlueprint(body: unknown): Blueprint | null {
  if (!isRecord(body) || !isId(body.company_id) || !isRecord(body.licensing) || !isRecord(body.jurisdiction)) {
    return null;
  }
  const { licensing, jurisdiction } = body;
  const count = body.employee_count;
  if (
    !optionalText(body.legal_name) ||
    !optionalText(body.industry) ||
    !(count === null || (typeof count === "number" && Number.isInteger(count) && count >= 0)) ||
    !(licensing.location === null || isLicensingLocation(licensing.location)) ||
    !optionalText(licensing.authority) ||
    typeof jurisdiction.readiness !== "string" ||
    !READINESS.has(jurisdiction.readiness) ||
    typeof jurisdiction.reason !== "string" ||
    !(jurisdiction.employment_jurisdiction === null || JURISDICTIONS.has(String(jurisdiction.employment_jurisdiction))) ||
    !optionalText(jurisdiction.confirmed_at) ||
    typeof jurisdiction.guidance_allowed !== "boolean" ||
    !optionalText(body.updated_at)
  ) {
    return null;
  }
  const readiness = jurisdiction.readiness as Readiness;
  return {
    companyId: body.company_id,
    legalName: body.legal_name,
    industry: body.industry,
    employeeCount: count as number | null,
    licensing: { location: licensing.location as LicensingLocation | null, authority: licensing.authority },
    jurisdiction: {
      readiness,
      reason: jurisdiction.reason,
      employmentJurisdiction: jurisdiction.employment_jurisdiction as string | null,
      confirmedAt: jurisdiction.confirmed_at,
      // Guidance only ever follows a supported, confirmed jurisdiction.
      guidanceAllowed: readiness === "supported_confirmed" && jurisdiction.guidance_allowed,
    },
    updatedAt: body.updated_at,
  };
}

export function parseRegistration(body: unknown): Registration | null {
  if (
    !isRecord(body) ||
    (body.outcome !== "created" && body.outcome !== "existing") ||
    !isId(body.company_id) ||
    !isId(body.membership_id) ||
    // A new registration always makes its founder company_admin. An earlier one
    // reports the role held now (an operator may have demoted the founder);
    // the ready page reads the Membership again either way.
    (body.outcome === "created" ? body.role !== "company_admin" : body.role !== "company_admin" && body.role !== "member")
  ) {
    return null;
  }
  return { outcome: body.outcome, companyId: body.company_id, membershipId: body.membership_id };
}

/**
 * The Companies the signed-in user may open: `GET /me/companies` (M1-10C).
 *
 * Compatibility: an API from before M1-10C has no such route (404). Only then,
 * and only if demo candidates are configured, each candidate is asked for
 * through the protected `GET /companies/{id}` and listed only when the API
 * authorizes it (the B4 demo behaviour). The candidates themselves grant nothing.
 */
export async function discoverWorkspaces(
  accessToken: string,
  config: AuthConfig,
  fetcher: Fetch = fetch,
): Promise<ApiResult<Workspace[]>> {
  const result = await apiCall(config, accessToken, fetcher, "/me/companies", parseWorkspaces);
  if (result.ok || result.failure !== "not_found") return result;
  if (config.demoCompanyIds.length === 0) return { ok: false, failure: "unavailable" };

  const lookups = await Promise.all(
    config.demoCompanyIds.map((id) =>
      apiCall(config, accessToken, fetcher, `/companies/${encodeURIComponent(id)}`, parseCompany),
    ),
  );
  // Fail closed: an expired token or an unreachable API never degrades to a partial list.
  for (const failure of ["unauthenticated", "unavailable"] as const) {
    if (lookups.some((lookup) => !lookup.ok && lookup.failure === failure)) return { ok: false, failure };
  }
  const workspaces: Workspace[] = [];
  config.demoCompanyIds.forEach((id, index) => {
    const lookup = lookups[index];
    // The API echoes the requested id; anything else is not trusted.
    if (lookup.ok && lookup.data.id === id) {
      workspaces.push({ companyId: id, name: lookup.data.name, membershipId: null, role: null });
    }
  });
  return workspaces.length > 0 ? { ok: true, data: workspaces } : { ok: false, failure: "forbidden" };
}

export type WorkspaceDetails = {
  company: Company;
  /** Null only against an API from before M1-10C (no membership or Blueprint routes). */
  membership: Membership | null;
  blueprint: Blueprint | null;
  cases: CaseSummary[];
};

/**
 * One authorized Company's workspace data. The Company id is only a resource
 * identifier: every request is authorized by the API (Membership and RLS).
 */
export async function getWorkspaceDetails(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkspaceDetails>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  const base = `/companies/${companyId}`;
  const [company, membership, blueprint, cases] = await Promise.all([
    apiCall(config, accessToken, fetcher, base, parseCompany),
    apiCall(config, accessToken, fetcher, `${base}/membership`, parseMembership),
    apiCall(config, accessToken, fetcher, `${base}/blueprint`, parseBlueprint),
    apiCall(config, accessToken, fetcher, `${base}/cases`, parseCases),
  ]);
  if (!company.ok) return { ok: false, failure: company.failure };
  if (company.data.id !== companyId) return { ok: false, failure: "forbidden" };
  for (const part of [membership, blueprint, cases]) {
    if (!part.ok && part.failure !== "not_found") return { ok: false, failure: part.failure };
  }
  return {
    ok: true,
    data: {
      company: company.data,
      membership: membership.ok && membership.data.companyId === companyId ? membership.data : null,
      blueprint: blueprint.ok && blueprint.data.companyId === companyId ? blueprint.data : null,
      cases: cases.ok ? cases.data : [],
    },
  };
}

/** `POST /company-registrations`: a body rebuilt from validated values only. */
export function registerCompany(
  accessToken: string,
  config: AuthConfig,
  payload: RegistrationPayload,
  fetcher: Fetch = fetch,
): Promise<ApiResult<Registration>> {
  return apiCall(config, accessToken, fetcher, "/company-registrations", parseRegistration, {
    method: "POST",
    body: payload,
  });
}

/** `PATCH /companies/{id}/blueprint` (administrators only, enforced by the API). */
export async function updateBlueprint(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  patch: BlueprintPatch,
  fetcher: Fetch = fetch,
): Promise<ApiResult<Blueprint>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  const result = await apiCall(config, accessToken, fetcher, `/companies/${companyId}/blueprint`, parseBlueprint, {
    method: "PATCH",
    body: patch,
  });
  if (result.ok && result.data.companyId !== companyId) return { ok: false, failure: "unavailable" };
  return result;
}

// --- guided workflow Cases (M2-01) ---------------------------------------------------

function workflowCasesPath(companyId: string, workflowKey: string): string | null {
  return UUID.test(companyId) && KEY.test(workflowKey)
    ? `/companies/${companyId}/workflows/${workflowKey}/cases`
    : null;
}

/** `GET /companies/{id}/workflows/{key}/cases`: the Company's Cases of one workflow. */
export async function listWorkflowCases(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  workflowKey: string,
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowCaseSummary[]>> {
  const path = workflowCasesPath(companyId, workflowKey);
  if (path === null) return { ok: false, failure: "forbidden" };
  return apiCall(config, accessToken, fetcher, path, parseCaseSummaries);
}

/**
 * `POST /companies/{id}/workflows/{key}/cases` (administrators only, enforced by
 * the API). 201 creates; a retry with the same `request_key` answers 200 with
 * the same Case; a reused key with other details is a conflict.
 */
export async function createWorkflowCase(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  workflowKey: string,
  payload: { title: string; request_key: string },
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowCaseSummary>> {
  const path = workflowCasesPath(companyId, workflowKey);
  if (path === null) return { ok: false, failure: "forbidden" };
  return apiCall(config, accessToken, fetcher, path, parseCaseSummary, { method: "POST", body: payload });
}

/** `GET /companies/{id}/cases/{caseId}/workflow`: the Case's guided view. */
export async function getCaseWorkflow(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId)) return { ok: false, failure: "not_found" };
  const result = await apiCall(config, accessToken, fetcher, `/companies/${companyId}/cases/${caseId}/workflow`, parseWorkflowView);
  if (result.ok && result.data.case.id !== caseId) return { ok: false, failure: "unavailable" };
  return result;
}

/**
 * `PUT /companies/{id}/cases/{caseId}/workflow/steps/{step}/answers`
 * (administrators only). A stale `expected_revision` is a conflict; a retry
 * with the same `submission_key` is applied once.
 */
export async function saveStepAnswers(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  stepKey: string,
  payload: { expected_revision: number; submission_key: string; answers: Record<string, string | null> },
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId) || !KEY.test(stepKey)) return { ok: false, failure: "not_found" };
  const result = await apiCall(
    config,
    accessToken,
    fetcher,
    `/companies/${companyId}/cases/${caseId}/workflow/steps/${stepKey}/answers`,
    parseWorkflowView,
    { method: "PUT", body: payload },
  );
  if (result.ok && result.data.case.id !== caseId) return { ok: false, failure: "unavailable" };
  return result;
}

/** Progression requests (M2-03): the employer's pathway choice or a stage transition. */
type ProgressionPayload = { expected_revision: number; request_key: string; acknowledged_warnings: string[] };

async function progressionCall(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  route: "pathway" | "transitions",
  payload: ProgressionPayload & ({ pathway: string } | { transition: string }),
  fetcher: Fetch,
): Promise<ApiResult<WorkflowView>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId)) return { ok: false, failure: "not_found" };
  const result = await apiCall(
    config,
    accessToken,
    fetcher,
    `/companies/${companyId}/cases/${caseId}/workflow/progression/${route}`,
    parseWorkflowView,
    { method: "POST", body: payload },
  );
  if (result.ok && result.data.case.id !== caseId) return { ok: false, failure: "unavailable" };
  return result;
}

/**
 * `POST /companies/{id}/cases/{caseId}/workflow/progression/pathway`
 * (administrators only). 200 whether the API recorded or refused the choice
 * (the view's `progression.attempt` says which); a stale revision, unmatched
 * acknowledgments or no installed rules are a conflict.
 */
export function selectPathway(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  payload: ProgressionPayload & { pathway: string },
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  return progressionCall(accessToken, config, companyId, caseId, "pathway", payload, fetcher);
}

/** `POST /companies/{id}/cases/{caseId}/workflow/progression/transitions` (administrators only). */
export function requestTransition(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  payload: ProgressionPayload & { transition: string },
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  return progressionCall(accessToken, config, companyId, caseId, "transitions", payload, fetcher);
}

/**
 * `POST /companies/{id}/cases/{caseId}/decisions` (administrators only, M2-04).
 * 200 with the Case view (a retry with the same `request_key` replays); a stale
 * `expected_revision` or a reused key with other content is a conflict.
 */
export async function recordDecision(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  payload: DecisionPayload,
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId)) return { ok: false, failure: "not_found" };
  const result = await apiCall(config, accessToken, fetcher, `/companies/${companyId}/cases/${caseId}/decisions`, parseWorkflowView, {
    method: "POST",
    body: payload,
  });
  if (result.ok && result.data.case.id !== caseId) return { ok: false, failure: "unavailable" };
  return result;
}

/**
 * `POST /companies/{id}/cases/{caseId}/decisions/{recordId}/corrections`
 * (administrators only, M2-04): a new version of the record's current version.
 * A record of another Case is not found; a version already replaced is a conflict.
 */
export async function correctDecision(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  recordId: string,
  payload: CorrectionPayload,
  fetcher: Fetch = fetch,
): Promise<ApiResult<WorkflowView>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId) || !UUID.test(recordId)) return { ok: false, failure: "not_found" };
  const result = await apiCall(
    config,
    accessToken,
    fetcher,
    `/companies/${companyId}/cases/${caseId}/decisions/${recordId}/corrections`,
    parseWorkflowView,
    { method: "POST", body: payload },
  );
  if (result.ok && result.data.case.id !== caseId) return { ok: false, failure: "unavailable" };
  return result;
}

/** `GET /companies/{id}/cases/{caseId}/history?before=…`: an older page of the unified history. */
export async function getCaseHistory(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  before: string | null,
  fetcher: Fetch = fetch,
): Promise<ApiResult<TimelinePage>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  if (!UUID.test(caseId)) return { ok: false, failure: "not_found" };
  if (before !== null && (before.length > 200 || !ENTRY_ID.test(before))) return { ok: false, failure: "invalid" };
  const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
  return apiCall(config, accessToken, fetcher, `/companies/${companyId}/cases/${caseId}/history${query}`, parseTimelinePage);
}

// --- document templates and previews (M2-04C) -----------------------------------------

function documentsPath(companyId: string, caseId: string, templateKey?: string): string | null {
  if (!UUID.test(companyId) || !UUID.test(caseId)) return null;
  if (templateKey === undefined) return `/companies/${companyId}/cases/${caseId}/documents`;
  return TEMPLATE_KEY.test(templateKey) ? `/companies/${companyId}/cases/${caseId}/documents/${templateKey}` : null;
}

/** `GET /companies/{id}/cases/{caseId}/documents`: every template and whether the Case can preview it now. */
export async function getCaseDocuments(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  fetcher: Fetch = fetch,
): Promise<ApiResult<DocumentsList>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  const path = documentsPath(companyId, caseId);
  if (path === null) return { ok: false, failure: "not_found" };
  return apiCall(config, accessToken, fetcher, path, fromApiDocumentsList);
}

/** `GET /companies/{id}/cases/{caseId}/documents/{template}`: an available template's form (409 if not available). */
export async function getDocumentForm(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  templateKey: string,
  fetcher: Fetch = fetch,
): Promise<ApiResult<TemplateForm>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  const path = documentsPath(companyId, caseId, templateKey);
  if (path === null) return { ok: false, failure: "not_found" };
  const result = await apiCall(config, accessToken, fetcher, path, fromApiTemplateForm);
  if (result.ok && result.data.template.key !== templateKey) return { ok: false, failure: "unavailable" };
  return result;
}

/**
 * `POST /companies/{id}/cases/{caseId}/documents/{template}/preview`: the
 * template filled with the employer's values (never stored). POST so personal
 * details never travel in a URL. 409 if the template isn't available now or
 * its version changed; 422 names the fields only.
 */
export async function previewDocument(
  accessToken: string,
  config: AuthConfig,
  companyId: string,
  caseId: string,
  templateKey: string,
  payload: PreviewPayload,
  fetcher: Fetch = fetch,
): Promise<ApiResult<Preview>> {
  if (!UUID.test(companyId)) return { ok: false, failure: "forbidden" };
  const path = documentsPath(companyId, caseId, templateKey);
  if (path === null) return { ok: false, failure: "not_found" };
  const result = await apiCall(config, accessToken, fetcher, `${path}/preview`, fromApiPreview, {
    method: "POST",
    body: payload,
  });
  if (result.ok && result.data.template.key !== templateKey) return { ok: false, failure: "unavailable" };
  return result;
}
