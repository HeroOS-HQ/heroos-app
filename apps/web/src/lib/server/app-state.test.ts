// @vitest-environment node
import { describe, expect, it } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";

import { discoveryState, workspaceState } from "./app-state";
import type { Workspace, WorkspaceDetails } from "./heroos-api";

const A: Workspace = { companyId: COMPANY_ID, name: "Alpha", membershipId: "m", role: "company_admin" };
const B: Workspace = { companyId: "d3e0b000-0000-4000-8000-000000000001", name: "Beta", membershipId: "n", role: "member" };
const DETAILS: WorkspaceDetails = { company: { id: COMPANY_ID, name: "Alpha" }, membership: null, blueprint: null, cases: [] };

describe("discoveryState", () => {
  it("opens a single workspace directly and offers a choice among several", () => {
    expect(discoveryState({ ok: true, data: [A] })).toEqual({ kind: "single", workspace: A });
    expect(discoveryState({ ok: true, data: [A, B] })).toEqual({ kind: "workspace_selection", workspaces: [A, B] });
  });

  it("an empty list is 'no active workspace', not a new founder", () => {
    expect(discoveryState({ ok: true, data: [] })).toEqual({ kind: "no_active_workspace" });
  });

  it("a 403 is 'unprovisioned or blocked': never treated as permission to register", () => {
    expect(discoveryState({ ok: false, failure: "forbidden" })).toEqual({ kind: "unprovisioned_or_blocked" });
  });

  it.each([
    ["unauthenticated", "session_expired"],
    ["unavailable", "api_unavailable"],
    ["not_found", "api_unavailable"],
    ["invalid", "api_unavailable"],
  ] as const)("maps %s to %s", (failure, kind) => {
    expect(discoveryState({ ok: false, failure })).toEqual({ kind });
  });
});

describe("workspaceState", () => {
  it("is ready only when the API authorized the Company", () => {
    expect(workspaceState({ ok: true, data: DETAILS }, { ok: true, data: [A, B] })).toEqual({
      kind: "workspace_ready",
      details: DETAILS,
      workspaces: [A, B],
    });
  });

  it("still opens the workspace when discovery for the switcher fails", () => {
    expect(workspaceState({ ok: true, data: DETAILS }, { ok: false, failure: "unavailable" })).toMatchObject({
      kind: "workspace_ready",
      workspaces: [],
    });
  });

  it.each([
    ["forbidden", "access_denied"],
    ["not_found", "access_denied"],
    ["invalid", "access_denied"],
    ["unauthenticated", "session_expired"],
    ["unavailable", "api_unavailable"],
  ] as const)("maps a %s workspace to %s (another Company looks like a missing one)", (failure, kind) => {
    expect(workspaceState({ ok: false, failure }, { ok: true, data: [A] })).toEqual({ kind });
  });
});
