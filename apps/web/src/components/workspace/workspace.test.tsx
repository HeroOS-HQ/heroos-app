import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/app/app-shell";
import { LoadingView } from "@/components/app/loading-view";
import {
  AccessDeniedView,
  NoActiveWorkspaceView,
  SessionExpiredView,
  SignedOutView,
  UnprovisionedView,
} from "@/components/app/state-views";
import type { Blueprint, Membership, WorkspaceDetails } from "@/lib/server/heroos-api";

import { WorkspaceChooser } from "./workspace-chooser";
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

  it("is the Complete stage: every earlier stage completed, Complete current", () => {
    render(<WorkspaceReady details={details()} outcome="created" />);
    const progress = screen.getByRole("list", { name: "Setup progress" });
    const stages = within(progress).getAllByRole("listitem");
    expect(stages.map((stage) => stage.textContent)).toEqual([
      "Welcome (completed)",
      "Company Basics (completed)",
      "Licence & Jurisdiction (completed)",
      "Review (completed)",
      "5Complete",
    ]);
    expect(stages[4]).toHaveAttribute("aria-current", "step");
    // Phones say it in words above the card; the card says it too.
    expect(screen.getAllByText("Step 5 of 5")).toHaveLength(2);
  });

  it("shows only what the API returned: the saved details, the licensing answer and an unconfirmed jurisdiction", () => {
    render(<WorkspaceReady details={details()} outcome="created" />);
    const status = screen.getByRole("region", { name: "Setup status" });
    expect(within(status).getByText(/Gamma Trading FZ-LLC · Retail · 1,200 employees/)).toBeInTheDocument();
    expect(within(status).getByText(/Other licensing authority · Example Free Zone Authority/)).toBeInTheDocument();
    expect(within(status).getByText("Not yet confirmed")).toBeInTheDocument();
    // No suggested law, upload receipt or activated templates.
    expect(document.body.textContent).not.toMatch(/UAE Federal|MOHRE|suggested|uploaded|templates? (are )?(active|ready)/i);
  });

  it("offers the three areas of the signed-in product as next steps", () => {
    render(<WorkspaceReady details={details()} outcome="created" />);
    const next = screen.getByRole("region", { name: "What you can do now" });
    expect(within(next).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      `/workspaces/${COMPANY_ID}`,
      `/workspaces/${COMPANY_ID}/settings`,
      `/workspaces/${COMPANY_ID}/space`,
    ]);
    expect(within(next).getAllByRole("link").map((link) => link.textContent)).toEqual(["Ask HeroOS", "Open Blueprint", "Open Company Space"]);
    expect(next.textContent).not.toMatch(/dashboard|HR services/i);
    expect(screen.getByRole("link", { name: "Edit company information" })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/settings`,
    );
    // No way back into a wizard whose draft no longer exists.
    expect(screen.queryByRole("button", { name: /Back/ })).toBeNull();
  });

  it("gives a member no edit actions", () => {
    render(<WorkspaceReady details={details({ membership: MEMBER })} outcome="existing" />);
    expect(screen.queryByRole("link", { name: /^Edit/ })).toBeNull();
    expect(screen.getByText("Available to view")).toBeInTheDocument();
    expect(screen.queryByText(/administrator/)).toBeNull();
  });

  it("an existing registration says the submission changed nothing, true even after an uncertain retry", () => {
    render(<WorkspaceReady details={details()} outcome="existing" />);
    expect(screen.getByRole("heading", { level: 1, name: "You already have a workspace" })).toBeInTheDocument();
    expect(screen.getByText("Your existing workspace wasn't changed")).toBeInTheDocument();
    expect(screen.getByText(/kept the details already on record/)).toBeInTheDocument();
    // Details are "on record", never "saved" by this submission.
    expect(within(screen.getByRole("region", { name: "Setup status" })).getAllByText(/^On record/)).toHaveLength(2);
    // Never claims the details are lost: an uncertain first attempt may have saved them.
    expect(document.body.textContent).not.toMatch(/workspace is ready|weren't saved|were not saved|are saved in/);
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
  it("signs out with a POST form and starts with the skip link", () => {
    const { container } = render(
      <AppShell>
        <p>content</p>
      </AppShell>,
    );
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("has the signed-in top bar's current HeroOS symbol, also while a page loads, never the old logo", () => {
    for (const view of [<AppShell key="shell">x</AppShell>, <LoadingView key="loading" />]) {
      const { container, unmount } = render(view);
      const logos = [...container.querySelector("header")!.querySelectorAll("img")].map((img) => img.getAttribute("src"));
      expect(logos).toContain("/branding/heroos-symbol.png");
      expect(logos).not.toContain("/branding/heroos-logo-symbol.png");
      unmount();
    }
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
