import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/app/app-shell";
import { CompanyFrame } from "@/components/app/company-frame";
import {
  AccessDeniedView,
  NoActiveWorkspaceView,
  SessionExpiredView,
  SignedOutView,
  UnprovisionedView,
} from "@/components/app/state-views";
import type { Blueprint, Membership, WorkspaceDetails } from "@/lib/server/heroos-api";

import { DisciplineOverview } from "./discipline-overview";
import { HrServices } from "./hr-services";
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
  it("welcomes the administrator to the company's dashboard and links to editing the company details", () => {
    render(<WorkspaceHome details={details()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Welcome to HeroOS");
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Edit company details/ })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/settings`,
    );
    const info = screen.getByRole("region", { name: "Your company at a glance" });
    expect(within(info).getByText("Gamma Trading")).toBeInTheDocument();
    expect(within(info).getByText("1,200")).toBeInTheDocument();
    expect(within(info).getByText("Example Free Zone Authority")).toBeInTheDocument();
    expect(within(info).getByText("Gamma Trading FZ-LLC")).toBeInTheDocument();
  });

  it("shows a missing detail as not provided instead of inventing one", () => {
    render(<WorkspaceHome details={details({ blueprint: { ...BLUEPRINT, industry: null, employeeCount: null } })} />);
    const info = screen.getByRole("region", { name: "Your company at a glance" });
    expect(within(info).getAllByText("Not provided")).toHaveLength(2);
  });

  it("gives an ordinary member a read-only view", () => {
    render(<WorkspaceHome details={details({ membership: MEMBER })} />);
    expect(screen.getByText("Member")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View company details/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Edit company details/ })).toBeNull();
    expect(screen.getByText("Only company administrators can change these details.")).toBeInTheDocument();
    // No way into the cases for a member, only the reason.
    expect(screen.queryByRole("link", { name: /Disciplinary cases/ })).toBeNull();
  });

  it("states an unconfirmed jurisdiction in words, without naming a regime", () => {
    render(<WorkspaceHome details={details()} />);
    const jurisdiction = screen.getByRole("region", { name: "Jurisdiction status" });
    expect(within(jurisdiction).getByRole("heading", { name: "Jurisdiction not yet confirmed" })).toBeInTheDocument();
    expect(within(jurisdiction).getByText("Not yet confirmed")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/MOHRE|UAE Federal|compliant|verified|eligible|suggest/i);
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
    expect(screen.getAllByText(/doesn't currently support guidance for this jurisdiction/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/subscri|upgrade|buy/i);
  });

  it("offers real next actions: HR Services, the company details and, for administrators, the cases", () => {
    render(<WorkspaceHome details={details()} />);
    const actions = screen.getByRole("region", { name: "What you can do now" });
    expect(within(actions).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      `/workspaces/${COMPANY_ID}/hr-services`,
      `/workspaces/${COMPANY_ID}/settings`,
      `/workspaces/${COMPANY_ID}/cases`,
    ]);
    // Nothing the product can't do yet (team invitations, reports, notifications).
    expect(document.body.textContent).not.toMatch(/invite|report|notification|template/i);
  });

  it("lists the HR services with their availability; only Disciplinary opens, for administrators", () => {
    render(<WorkspaceHome details={details()} />);
    const workflows = screen.getByRole("region", { name: "HR services" });
    expect(within(workflows).getByText("Conduct & Discipline")).toBeInTheDocument();
    const links = within(workflows).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/disciplinary`);
    expect(links[0]).toHaveTextContent("Limited");
    expect(links[0]).toHaveTextContent("jurisdiction-specific steps wait for confirmation");
    expect(within(workflows).getAllByText("Coming soon")).toHaveLength(2);
    expect(within(workflows).queryAllByRole("button")).toHaveLength(0);
  });

  it("shows Disciplinary as administrator-only to a member, with nothing to click", () => {
    render(<WorkspaceHome details={details({ membership: MEMBER })} />);
    const workflows = screen.getByRole("region", { name: "HR services" });
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
    expect(screen.queryByRole("link", { name: /company details|Company Blueprint/ })).toBeNull();
    expect(screen.queryByRole("region", { name: "Jurisdiction status" })).toBeNull();
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
    render(<WorkspaceHome details={details()} />);
    expect(within(screen.getByRole("list", { name: "Company setup" })).getAllByRole("listitem")).toHaveLength(4);
  });
});

describe("HrServices", () => {
  it("shows the three workflows; Disciplinary opens its overview, the others are honestly not available", () => {
    render(<HrServices details={details()} />);
    expect(screen.getByRole("heading", { level: 1, name: "HR Services" })).toBeInTheDocument();
    const workflows = screen.getByRole("list", { name: "HR workflows" });
    expect(within(workflows).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Conduct & Discipline",
      "Probation",
      "Recruitment",
    ]);
    expect(within(workflows).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      `/workspaces/${COMPANY_ID}/disciplinary`,
    ]);
    expect(within(workflows).getAllByText("Coming soon")).toHaveLength(2);
    // No "Learn more" or other actions for what isn't there.
    expect(within(workflows).queryByText(/learn more/i)).toBeNull();
    expect(document.body.textContent).not.toMatch(/generate|automatic|guarantee|compliant/i);
  });

  it("asks for the jurisdiction first while it is unconfirmed, and not once it is confirmed", () => {
    const { unmount } = render(<HrServices details={details()} />);
    expect(screen.getByRole("link", { name: /View jurisdiction details/ })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/settings`,
    );
    unmount();
    const confirmed: Blueprint = {
      ...BLUEPRINT,
      jurisdiction: { ...BLUEPRINT.jurisdiction, readiness: "supported_confirmed", employmentJurisdiction: "uae_federal", guidanceAllowed: true },
    };
    render(<HrServices details={details({ blueprint: confirmed })} />);
    expect(screen.queryByRole("link", { name: /View jurisdiction details/ })).toBeNull();
    expect(screen.getByText("In development")).toBeInTheDocument();
  });

  it("makes the workflow that can be opened the primary action; the jurisdiction link stays secondary", () => {
    render(<HrServices details={details()} />);
    const open = screen.getByRole("link", { name: /View details/ });
    const jurisdiction = screen.getByRole("link", { name: /View jurisdiction details/ });
    expect(open.className).toContain("bg-hero-yellow");
    expect(jurisdiction.className).not.toContain("bg-hero-yellow");
    expect(jurisdiction.className).toContain("border-hero-control");
    // Nothing yellow for what can't be opened.
    for (const unavailable of ["Probation", "Recruitment"]) {
      const card = screen.getByRole("heading", { name: unavailable }).closest("li")!;
      expect(within(card).queryByRole("link")).toBeNull();
    }
  });

  it("gives a member no way into Disciplinary", () => {
    render(<HrServices details={details({ membership: MEMBER })} />);
    expect(within(screen.getByRole("list", { name: "HR workflows" })).queryAllByRole("link")).toHaveLength(0);
    expect(screen.getAllByText("Administrators only").length).toBeGreaterThan(0);
  });
});

describe("DisciplineOverview", () => {
  it("describes the product's own steps, never the review mockup's legal stages, and links the real routes", () => {
    render(<DisciplineOverview cases={[]} details={details()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Conduct & Discipline" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("HR Services");
    expect(document.body.textContent).not.toMatch(/written warning|termination|hearing|grievance|less serious|serious misconduct/i);
    expect(screen.getByRole("link", { name: /Create a new disciplinary case/ })).toHaveAttribute(
      "href",
      `/workspaces/${COMPANY_ID}/cases/new`,
    );
    const availability = screen.getByRole("region", { name: "Workflow availability" });
    expect(within(availability).getByText("Restricted")).toBeInTheDocument();
    expect(within(availability).getByText("Not available")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Guided steps need a confirmed jurisdiction first." })).toBeInTheDocument();
    expect(screen.getByText(/No cases yet/)).toBeInTheDocument();
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
});

describe("CompanyFrame", () => {
  const frame = (props: Partial<Parameters<typeof CompanyFrame>[0]> = {}) =>
    render(
      <CompanyFrame
        admin
        companies={[{ companyId: COMPANY_ID, name: "Alpha" }]}
        companyId={COMPANY_ID}
        companyName="Alpha"
        current="dashboard"
        role="Administrator"
        {...props}
      >
        <p>content</p>
      </CompanyFrame>,
    );

  it("shows the only company by name (no menu), signs out with a POST form and skips to the content", () => {
    const { container } = frame();
    expect(screen.queryByRole("button", { name: /Switch company/ })).toBeNull();
    expect(within(screen.getByRole("banner")).getByText("Alpha")).toBeInTheDocument();
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveTextContent("content");
  });

  it("navigates the company's real routes and marks the current one; what doesn't exist yet is not a link", () => {
    frame({ current: "services" });
    const nav = screen.getByRole("navigation", { name: "Company" });
    expect(within(nav).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Dashboard", `/workspaces/${COMPANY_ID}`],
      ["Company Blueprint", `/workspaces/${COMPANY_ID}/settings`],
      ["HR Services", `/workspaces/${COMPANY_ID}/hr-services`],
      ["Cases", `/workspaces/${COMPANY_ID}/cases`],
    ]);
    expect(within(nav).getByRole("link", { current: "page" })).toHaveTextContent("HR Services");
    expect(within(nav).getByText("Team & Access").closest("a")).toBeNull();
    expect(within(nav).getByText("Coming soon")).toBeInTheDocument();
  });

  it("doesn't link a member to the cases", () => {
    frame({ admin: false, role: "Member" });
    const nav = screen.getByRole("navigation", { name: "Company" });
    expect(within(nav).queryByRole("link", { name: "Cases" })).toBeNull();
    expect(within(nav).getByText("Administrators only")).toBeInTheDocument();
  });

  it("switches only among the listed companies and closes with Escape", () => {
    frame({
      companies: [
        { companyId: COMPANY_ID, name: "Alpha" },
        { companyId: COMPANY_B, name: "Beta" },
      ],
    });
    const toggle = screen.getByRole("button", { name: /Switch company/ });
    expect(toggle).toHaveTextContent("Alpha");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const nav = screen.getByRole("navigation", { name: "Your companies" });
    expect(within(nav).getByRole("link", { name: "Alpha" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Beta" })).toHaveAttribute("href", `/workspaces/${COMPANY_B}`);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Your companies" })).toBeNull();
    expect(toggle).toHaveFocus();
  });

  it("opens the navigation as a panel on small screens; Escape closes it and returns focus", async () => {
    frame();
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(screen.getByRole("button", { name: "Close the menu" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(menu).toHaveFocus());
  });

  it("leaves the side to the case workspace in case mode (never two sidebars)", () => {
    frame({ mode: "case" });
    expect(screen.queryByRole("navigation", { name: "Company" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Menu" })).toBeNull();
    expect(screen.getByRole("main")).toHaveTextContent("content");
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
