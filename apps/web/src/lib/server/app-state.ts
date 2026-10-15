import "server-only";

import { readAuthConfig, type AuthConfig } from "./config";
import type { CaseSummary as WorkflowCaseSummary, WorkflowView } from "@/lib/workflows/model";

import {
  type ApiResult,
  discoverWorkspaces,
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
    };

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

export function casesState(
  details: ApiResult<WorkspaceDetails>,
  workspaces: ApiResult<Workspace[]>,
  cases: ApiResult<WorkflowCaseSummary[]>,
): CasesState {
  const workspace = workspaceState(details, workspaces);
  if (workspace.kind !== "workspace_ready") return workspace;
  const base = { details: workspace.details, workspaces: workspace.workspaces };
  if (!cases.ok) {
    return cases.failure === "not_found" ? { kind: "workflow_unavailable", ...base } : failureState(cases.failure);
  }
  return { kind: "cases_ready", ...base, cases: cases.data };
}

export function caseState(
  details: ApiResult<WorkspaceDetails>,
  workspaces: ApiResult<Workspace[]>,
  cases: ApiResult<WorkflowCaseSummary[]>,
  view: ApiResult<WorkflowView>,
): CaseState {
  const list = casesState(details, workspaces, cases);
  if (list.kind !== "cases_ready") return list;
  const base = { details: list.details, workspaces: list.workspaces, cases: list.cases };
  if (!view.ok) return view.failure === "not_found" ? { kind: "case_not_found", ...base } : failureState(view.failure);
  return { kind: "case_ready", ...base, view: view.data };
}

/** The Company's Cases of one workflow (the URL id is only a resource identifier). */
export async function loadCases(companyId: string, workflowKey: string): Promise<CasesState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  const [details, workspaces, cases] = await Promise.all([
    getWorkspaceDetails(gate.accessToken, gate.config, companyId),
    discoverWorkspaces(gate.accessToken, gate.config),
    listWorkflowCases(gate.accessToken, gate.config, companyId, workflowKey),
  ]);
  return casesState(details, workspaces, cases);
}

/** One workflow Case with its sidebar list; every request is authorized by the API. */
export async function loadCase(companyId: string, workflowKey: string, caseId: string): Promise<CaseState> {
  const gate = await sessionGate();
  if (gate.kind !== "ok") return gate;
  const [details, workspaces, cases, view] = await Promise.all([
    getWorkspaceDetails(gate.accessToken, gate.config, companyId),
    discoverWorkspaces(gate.accessToken, gate.config),
    listWorkflowCases(gate.accessToken, gate.config, companyId, workflowKey),
    getCaseWorkflow(gate.accessToken, gate.config, companyId, caseId),
  ]);
  return caseState(details, workspaces, cases, view);
}
