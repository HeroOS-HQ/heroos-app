import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/app/app-shell";
import {
  AccessDeniedView,
  NoActiveWorkspaceView,
  SessionExpiredView,
  SignedOutView,
  UnprovisionedView,
} from "@/components/app/state-views";
import type { Blueprint, Membership, WorkspaceDetails } from "@/lib/server/heroos-api";

import { WorkspaceChooser } from "./workspace-chooser";
import { setupSteps, WorkspaceHome } from "./workspace-home";
import { WorkspaceReady } from "./workspace-ready";

const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";
const COMPANY_B = "d3e0b000-0000-4000-8000-000000000001";

const BLUEPRINT: Blueprint = {
  companyId: COMPANY_ID,
  legalName: "Gamma Trading FZ-LLC",
  industry: "Retail",
  employeeCount: 1200,
  licensing: { location: "other", authority: "Example Free Zone Authority" },
  jurisdiction: {
    readiness: "unconfirmed",
    reason: "awaiting_confirmation",
    employmentJurisdiction: null,
    confirmedAt: null,
    guidanceAllowed: false,
  },
  updatedAt: null,
};
const ADMIN: Membership = { companyId: COMPANY_ID, membershipId: "m", role: "company_admin", canUpdateBlueprint: true };
const MEMBER: Membership = { ...ADMIN, role: "member", canUpdateBlueprint: false };

const details = (overrides: Partial<WorkspaceDetails> = {}): WorkspaceDetails => ({
  company: { id: COMPANY_ID, name: "Gamma Trading" },
  membership: ADMIN,
  blueprint: BLUEPRINT,
  cases: [],
  ...overrides,
});

describe("WorkspaceHome", () => {
  it("welcomes the administrator and links to editing the company details", () => {
    render(<WorkspaceHome details={details()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Gamma Trading" })).toBeInTheDocument();
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Edit company details/ })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/settings`,
    );
    const info = screen.getByRole("region", { name: "Company information" });
    expect(within(info).getByText("1,200")).toBeInTheDocument();
    expect(within(info).getByText("Example Free Zone Authority")).toBeInTheDocument();
  });

  it("gives an ordinary member a read-only view", () => {
    render(<WorkspaceHome details={details({ membership: MEMBER })} />);
    expect(screen.getByText("Member")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View company details/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Edit company details/ })).toBeNull();
    expect(screen.getByText("Only company administrators can change these details.")).toBeInTheDocument();
  });

  it("states an unconfirmed jurisdiction in words, without naming a regime", () => {
    render(<WorkspaceHome details={details()} />);
    const info = screen.getByRole("region", { name: "Company information" });
    expect(within(info).getByRole("heading", { name: "Jurisdiction not yet confirmed" })).toBeInTheDocument();
    expect(within(info).getByText("Not yet confirmed")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/MOHRE|UAE Federal|compliant|verified|eligible/);
  });

  it("explains an unsupported confirmed jurisdiction and offers nothing for it", () => {
    const unsupported: Blueprint = {
      ...BLUEPRINT,
      jurisdiction: {
        readiness: "unsupported",
        reason: "jurisdiction_not_supported",
        employmentJurisdiction: "adgm",
        confirmedAt: "2026-10-14T09:00:00Z",
        guidanceAllowed: false,
      },
    };
    render(<WorkspaceHome details={details({ blueprint: unsupported })} />);
    expect(screen.getByRole("heading", { name: "ADGM isn't supported yet" })).toBeInTheDocument();
    expect(screen.getByText(/doesn't currently support guidance for this jurisdiction/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/subscri|upgrade|buy/i);
  });

  it("opens Disciplinary (intake only) and shows the other workflows as coming soon", () => {
    render(<WorkspaceHome details={details()} />);
    const workflows = screen.getByRole("region", { name: "HR workflows" });
    expect(within(workflows).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Disciplinary",
      "Probation",
      "Recruitment",
    ]);
    // Only Disciplinary is a link, and it says how far it goes.
    const links = within(workflows).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", `/workspaces/${details().company.id}/cases`);
    expect(links[0]).toHaveTextContent("In development");
    expect(within(workflows).getAllByText("Coming soon")).toHaveLength(2);
    expect(within(workflows).queryAllByRole("button")).toHaveLength(0);
  });

  it("shows Disciplinary as administrator-only to a member, with nothing to click", () => {
    render(<WorkspaceHome details={details({ membership: MEMBER })} />);
    const workflows = screen.getByRole("region", { name: "HR workflows" });
    expect(within(workflows).queryAllByRole("link")).toHaveLength(0);
    expect(within(workflows).getByText("Administrators only")).toBeInTheDocument();
    expect(within(workflows).getAllByText("Coming soon")).toHaveLength(2);
  });

  it("links saved Disciplinary cases to the guided workspace, other records stay read-only", () => {
    render(
      <WorkspaceHome
        details={details({
          cases: [
            { id: "c1", title: "[SYNTHETIC] Disciplinary", caseType: "disciplinary", createdAt: "x" },
            { id: "c2", title: "[SYNTHETIC] Other", caseType: "general", createdAt: "x" },
          ],
        })}
      />,
    );
    const list = screen.getByRole("list", { name: "Cases" });
    expect(within(list).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      `/workspaces/${details().company.id}/cases/c1`,
    ]);
  });

  it("lists saved case records only when there are some", () => {
    const { rerender } = render(<WorkspaceHome details={details()} />);
    expect(screen.queryByRole("list", { name: "Cases" })).toBeNull();
    rerender(
      <WorkspaceHome
        details={details({ cases: [{ id: "1", title: "[SYNTHETIC DEMO] Case A-1", caseType: "general", createdAt: "x" }] })}
      />,
    );
    expect(screen.getByRole("list", { name: "Cases" })).toHaveTextContent("[SYNTHETIC DEMO] Case A-1");
  });

  it("still opens against an API without company profiles (legacy demo)", () => {
    render(<WorkspaceHome details={details({ membership: null, blueprint: null })} />);
    expect(screen.getByText("Company profile isn't available yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /company details/ })).toBeNull();
  });

  it("describes setup progress in words", () => {
    expect(setupSteps(BLUEPRINT).map((step) => `${step.label}: ${step.status}`)).toEqual([
      "Workspace created: Done",
      "Company details: Added",
      "Licensing details: Provided",
      "Jurisdiction: Not yet confirmed",
    ]);
    expect(
      setupSteps({ ...BLUEPRINT, licensing: { location: "not_sure", authority: null } })[2].status,
    ).toBe("Not sure yet");
    expect(setupSteps({ ...BLUEPRINT, licensing: { location: "other", authority: null } })[2].status).toBe(
      "Authority missing",
    );
  });
});

describe("WorkspaceReady", () => {
  it("confirms creation with the API's company name and opens the workspace", () => {
    render(<WorkspaceReady details={details()} outcome="created" />);
    expect(screen.getByRole("heading", { level: 1, name: "Your workspace is ready" })).toBeInTheDocument();
    expect(screen.getByText("Gamma Trading")).toBeInTheDocument();
    expect(screen.getByText(/you're its administrator/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open my workspace/ })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}`);
    // Workspace creation is not a jurisdiction confirmation.
    expect(screen.getByRole("heading", { name: "Jurisdiction not yet confirmed" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/compliant|verified|approved|ready for legal advice/i);
  });

  it("an existing registration says the submission changed nothing, true even after an uncertain retry", () => {
    render(<WorkspaceReady details={details()} outcome="existing" />);
    expect(screen.getByRole("heading", { level: 1, name: "You already have a workspace" })).toBeInTheDocument();
    expect(screen.getByText("Your existing workspace wasn't changed")).toBeInTheDocument();
    expect(screen.getByText(/kept the details already on record/)).toBeInTheDocument();
    // Never claims the details are lost: an uncertain first attempt may have saved them.
    expect(document.body.textContent).not.toMatch(/workspace is ready|weren't saved|were not saved/);
  });
});

describe("WorkspaceChooser", () => {
  it("lists only the given workspaces, with roles, as full-page links", () => {
    render(
      <WorkspaceChooser
        workspaces={[
          { companyId: COMPANY_ID, name: "Alpha", membershipId: "m", role: "company_admin" },
          { companyId: COMPANY_B, name: "Beta", membershipId: "n", role: "member" },
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Your workspaces" });
    expect(within(list).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      `/workspaces/${COMPANY_ID}`,
      `/workspaces/${COMPANY_B}`,
    ]);
    expect(within(list).getByText("Administrator")).toBeInTheDocument();
    expect(within(list).getByText("Member")).toBeInTheDocument();
  });
});

describe("AppShell", () => {
  it("signs out with a POST form and hides the switcher for a single workspace", () => {
    const { container } = render(
      <AppShell switcher={{ currentId: COMPANY_ID, items: [{ companyId: COMPANY_ID, name: "Alpha" }] }}>
        <p>content</p>
      </AppShell>,
    );
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.queryByRole("button", { name: "Switch company" })).toBeNull();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("switches only among the listed companies and closes with Escape", () => {
    render(
      <AppShell
        switcher={{
          currentId: COMPANY_ID,
          items: [
            { companyId: COMPANY_ID, name: "Alpha" },
            { companyId: COMPANY_B, name: "Beta" },
          ],
        }}
      >
        <p>content</p>
      </AppShell>,
    );
    const toggle = screen.getByRole("button", { name: "Switch company" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const nav = screen.getByRole("navigation", { name: "Your companies" });
    expect(within(nav).getByRole("link", { name: "Alpha" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Beta" })).toHaveAttribute("href", `/workspaces/${COMPANY_B}`);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Your companies" })).toBeNull();
    expect(toggle).toHaveFocus();
  });
});

describe("state views", () => {
  it("an unknown identity gets a neutral welcome; only a click starts onboarding", () => {
    const { container } = render(<UnprovisionedView />);
    expect(screen.getByRole("link", { name: "Set up my company" })).toHaveAttribute("href", "/onboarding");
    // Nothing registers automatically: the only form is sign-out.
    expect([...container.querySelectorAll("form")].map((form) => form.getAttribute("action"))).toEqual(["/auth/logout"]);
    expect(screen.getByText(/Your access may have changed/)).toBeInTheDocument();
  });

  it("a known account without access is not promised a workspace", () => {
    render(<NoActiveWorkspaceView />);
    expect(screen.getByRole("heading", { name: "No active workspace" })).toBeInTheDocument();
    expect(screen.getByText(/doesn't currently have access/)).toBeInTheDocument();
  });

  it("access denied looks the same for any workspace the account can't open", () => {
    render(<AccessDeniedView />);
    expect(screen.getByRole("alert")).toHaveTextContent("You don't have access to this workspace");
    expect(screen.getByRole("link", { name: "Go to my workspaces" })).toHaveAttribute("href", "/workspaces");
  });

  it("an ended session offers sign-in", () => {
    render(<SessionExpiredView />);
    expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/login");
  });

  it("signed-out onboarding offers hosted sign-up and sign-in", () => {
    render(<SignedOutView purpose="onboarding" />);
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/auth/signup");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/auth/login");
  });
});
