import "server-only";

import { readAuthConfig, type AuthConfig } from "./config";
import { ASSISTANT_HIDDEN, type AssistantLoad, type AssistantStatus, assistantLoadOf } from "@/lib/assistant/model";
import type { CaseSummary as WorkflowCaseSummary, WorkflowView } from "@/lib/workflows/model";

import {
  type ApiResult,
  discoverWorkspaces,
  getAssistantStatus,
  getCaseWorkflow,
  getWorkspaceDetails,
  listWorkflowCases,
  type Workspace,
  type WorkspaceDetails,
} from "./heroos-api";
import { readSession } from "./session";

/**
 * Explicit, testable states for the signed-in app (M1-10D). Each page loads
 * one of these on the server and renders it; there is no other source of
 * authorization than the HeroOS API's answers.
 *
 * Important distinction: `GET /me/companies` answers 403 both for an identity
 * HeroOS does not know yet *and* for a suspended or revoked one. A 403 is
 * therefore never treated as permission to register: the page offers a
 * neutral way into onboarding, and the registration API decides.
 */

export type SessionGate =
  | { kind: "not_configured" }
  | { kind: "signed_out" }
  | { kind: "ok"; config: AuthConfig; accessToken: string };

/** Configuration plus the browser session (never exposes the token to rendering). */
export async function sessionGate(): Promise<SessionGate> {
  const configured = readAuthConfig();
  if (!configured.ok) return { kind: "not_configured" };
  const session = await readSession(configured.config);
  if (session === null) return { kind: "signed_out" };
  return { kind: "ok", config: configured.config, accessToken: session.accessToken };
}

export type DiscoveryState =
  | { kind: "not_configured" }
  | { kind: "signed_out" }
  | { kind: "session_expired" }
  /** AUTHENTICATED_UNPROVISIONED, or a suspended/revoked identity: indistinguishable by design. */
  | { kind: "unprovisioned_or_blocked" }
  /** NO_ACTIVE_WORKSPACE: a known User without any active Membership. */
  | { kind: "no_active_workspace" }
  | { kind: "single"; workspace: Workspace }
  | { kind: "workspace_selection"; workspaces: Workspace[] }
  | { kind: "api_unavailable" };

export function discoveryState(result: ApiResult<Workspace[]>): DiscoveryState {
  if (result.ok) {
    if (result.data.length === 0) return { kind: "no_active_workspace" };
    if (result.data.length === 1) return { kind: "single", workspace: result.data[0] };
    return { kind: "workspace_selection", workspaces: result.data };
  }
  switch (result.failure) {
    case "unauthenticated":
      return { kind: "session_expired" };
    case "forbidden":
      return { kind: "unprovisioned_or_blocked" };
    default:
      return { kind: "api_unavailable" };
  }
}

/**
 * Where onboarding sends someone straight after hosted sign-up: an account that
 * turns out to have a workspace already (an existing user who chose "Get
 * started", then signed in) goes to it. Every other state stays on onboarding,
 * where only the registration API decides eligibility.
 */
export function afterSignupRedirect(state: DiscoveryState): "/workspaces" | null {
  return state.kind === "single" || state.kind === "workspace_selection" ? "/workspaces" : null;
}

export async function loadDiscovery(): Promise<DiscoveryState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  return discoveryState(await discoverWorkspaces(gate.accessToken, gate.config));
}

export type WorkspaceState =
  | { kind: "not_configured" }
  | { kind: "signed_out" }
  | { kind: "session_expired" }
  /** ACCESS_DENIED: no active Membership (another Company, revoked, or unknown id). */
  | { kind: "access_denied" }
  | { kind: "api_unavailable" }
  | { kind: "workspace_ready"; details: WorkspaceDetails; workspaces: Workspace[] };

export function workspaceState(
  details: ApiResult<WorkspaceDetails>,
  workspaces: ApiResult<Workspace[]>,
): WorkspaceState {
  if (!details.ok) {
    switch (details.failure) {
      case "unauthenticated":
        return { kind: "session_expired" };
      case "unavailable":
        return { kind: "api_unavailable" };
      default:
        return { kind: "access_denied" };
    }
  }
  return { kind: "workspace_ready", details: details.data, workspaces: workspaces.ok ? workspaces.data : [] };
}

/** One Company's workspace. The id comes from the URL and is only a resource identifier. */
export async function loadWorkspace(companyId: string): Promise<WorkspaceState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  const [details, workspaces] = await Promise.all([
    getWorkspaceDetails(gate.accessToken, gate.config, companyId),
    discoverWorkspaces(gate.accessToken, gate.config),
  ]);
  return workspaceState(details, workspaces);
}

// --- guided workflow Cases (M2-01) ---------------------------------------------------

export type CasesState =
  | Exclude<WorkspaceState, { kind: "workspace_ready" }>
  /** M2-01 interim policy: Disciplinary Cases are for Company administrators only. */
  | { kind: "admin_only"; details: WorkspaceDetails; workspaces: Workspace[] }
  /** The HeroOS API serving this app has no workflow routes yet (an older deployment). */
  | { kind: "workflow_unavailable"; details: WorkspaceDetails; workspaces: Workspace[] }
  | { kind: "cases_ready"; details: WorkspaceDetails; workspaces: Workspace[]; cases: WorkflowCaseSummary[] };

export type CaseState =
  | Exclude<CasesState, { kind: "cases_ready" }>
  /** Not a workflow Case of this Company (identical for another Company's Case). */
  | { kind: "case_not_found"; details: WorkspaceDetails; workspaces: Workspace[]; cases: WorkflowCaseSummary[] }
  | {
      kind: "case_ready";
      details: WorkspaceDetails;
      workspaces: Workspace[];
      cases: WorkflowCaseSummary[];
      view: WorkflowView;
      /** The Hannah AI demo for this administrator and Case (read with the Case, so the first paint is right). */
      assistant: AssistantLoad;
    };

/** The API's answer for this Company; never a client-side grant of anything. */
export const isCompanyAdmin = (details: WorkspaceDetails) => details.membership?.role === "company_admin";

function failureState(failure: string): Exclude<WorkspaceState, { kind: "workspace_ready" }> {
  switch (failure) {
    case "unauthenticated":
      return { kind: "session_expired" };
    case "unavailable":
      return { kind: "api_unavailable" };
    default:
      return { kind: "access_denied" };
  }
}

/**
 * `cases` is null when it was not requested: case data is never asked for on
 * behalf of a non-administrator (the API refuses it too). A 403 from the
 * workflow routes means the caller is no longer an administrator.
 */
export function casesState(
  details: ApiResult<WorkspaceDetails>,
  workspaces: ApiResult<Workspace[]>,
  cases: ApiResult<WorkflowCaseSummary[]> | null,
): CasesState {
  const workspace = workspaceState(details, workspaces);
  if (workspace.kind !== "workspace_ready") return workspace;
  const base = { details: workspace.details, workspaces: workspace.workspaces };
  if (cases === null || !isCompanyAdmin(workspace.details)) return { kind: "admin_only", ...base };
  if (!cases.ok) {
    if (cases.failure === "not_found") return { kind: "workflow_unavailable", ...base };
    if (cases.failure === "forbidden") return { kind: "admin_only", ...base };
    return failureState(cases.failure);
  }
  return { kind: "cases_ready", ...base, cases: cases.data };
}

export function caseState(
  details: ApiResult<WorkspaceDetails>,
  workspaces: ApiResult<Workspace[]>,
  cases: ApiResult<WorkflowCaseSummary[]> | null,
  view: ApiResult<WorkflowView> | null,
  assistant: AssistantLoad = ASSISTANT_HIDDEN,
): CaseState {
  const list = casesState(details, workspaces, cases);
  if (list.kind !== "cases_ready") return list;
  const base = { details: list.details, workspaces: list.workspaces, cases: list.cases };
  if (view === null) return { kind: "admin_only", details: base.details, workspaces: base.workspaces };
  if (!view.ok) {
    if (view.failure === "not_found") return { kind: "case_not_found", ...base };
    if (view.failure === "forbidden") return { kind: "admin_only", details: base.details, workspaces: base.workspaces };
    return failureState(view.failure);
  }
  return { kind: "case_ready", ...base, view: view.data, assistant };
}

/**
 * The Hannah AI demo's status as the case page shows it. A refusal, an
 * unknown Case or an API without the demo keeps it out of sight; a waking or
 * failing API (or an answer this page can't read) is `unreachable`, which the
 * page says plainly. Never a reason to fail the Case page itself.
 */
export function assistantLoad(result: ApiResult<AssistantStatus>): AssistantLoad {
  if (result.ok) return assistantLoadOf(result.data);
  return result.failure === "unavailable" ? { state: "unreachable" } : ASSISTANT_HIDDEN;
}

/** The Company's Cases of one workflow (the URL id is only a resource identifier). */
export async function loadCases(companyId: string, workflowKey: string): Promise<CasesState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  const [details, workspaces] = await Promise.all([
    getWorkspaceDetails(gate.accessToken, gate.config, companyId),
    discoverWorkspaces(gate.accessToken, gate.config),
  ]);
  const admin = details.ok && isCompanyAdmin(details.data);
  const cases = admin ? await listWorkflowCases(gate.accessToken, gate.config, companyId, workflowKey) : null;
  return casesState(details, workspaces, cases);
}

/** One workflow Case with its sidebar list; every request is authorized by the API. */
export async function loadCase(companyId: string, workflowKey: string, caseId: string): Promise<CaseState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  const [details, workspaces] = await Promise.all([
    getWorkspaceDetails(gate.accessToken, gate.config, companyId),
    discoverWorkspaces(gate.accessToken, gate.config),
  ]);
  if (!(details.ok && isCompanyAdmin(details.data))) return caseState(details, workspaces, null, null);
  const [cases, view, assistant] = await Promise.all([
    listWorkflowCases(gate.accessToken, gate.config, companyId, workflowKey),
    getCaseWorkflow(gate.accessToken, gate.config, companyId, caseId),
    getAssistantStatus(gate.accessToken, gate.config, companyId, caseId),
  ]);
  return caseState(details, workspaces, cases, view, assistantLoad(assistant));
}
