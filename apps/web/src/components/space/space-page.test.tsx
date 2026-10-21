import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Blueprint, Membership, WorkspaceDetails } from "@/lib/server/heroos-api";
import { COMPANY_ID, NO_COMPANY_CONTEXT } from "@/test/fixtures";

import { monogram, SpacePage } from "./space-page";

const BLUEPRINT: Blueprint = {
  companyId: COMPANY_ID,
  legalName: "Bush & Bush Law Group",
  industry: "Legal and professional services",
  employeeCount: 24,
  licensing: { location: "difc", authority: null },
  jurisdiction: {
    readiness: "supported_confirmed",
    reason: "confirmed",
    employmentJurisdiction: "difc",
    confirmedAt: "2026-10-14T09:00:00Z",
    guidanceAllowed: true,
  },
  updatedAt: "2026-10-16T09:00:00Z",  ...NO_COMPANY_CONTEXT,
};
const ADMIN: Membership = { companyId: COMPANY_ID, membershipId: "m", role: "company_admin", canUpdateBlueprint: true };
const MEMBER: Membership = { ...ADMIN, role: "member", canUpdateBlueprint: false };
const details = (overrides: Partial<WorkspaceDetails> = {}): WorkspaceDetails => ({
  company: { id: COMPANY_ID, name: "Bush & Bush" },
  membership: ADMIN,
  blueprint: BLUEPRINT,
  cases: [],
  ...overrides,
});

describe("SpacePage (Company Space)", () => {
  it("introduces the company from the API's answer", () => {
    render(<SpacePage details={details()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Bush & Bush" })).toBeInTheDocument();
    expect(screen.getByText("Company Space")).toBeInTheDocument();
    expect(screen.getByText(/Legal and professional services · DIFC/)).toBeInTheDocument();
    // Back to Ask HeroOS at the top, and once more at the end: the place for any HR question.
    for (const link of screen.getAllByRole("link", { name: "Ask HeroOS" })) {
      expect(link).toHaveAttribute("href", `/workspaces/${COMPANY_ID}`);
    }
  });

  it("shows this account's access from its role, never a plan, price or limit", () => {
    render(<SpacePage details={details()} />);
    const access = within(screen.getByRole("region", { name: "Your access" }));
    expect(access.getByText("Company administrator")).toBeInTheDocument();
    expect(access.getByText("Active")).toBeInTheDocument();
    const services = access.getAllByRole("listitem").map((item) => item.textContent);
    expect(services).toEqual([
      expect.stringMatching(/Ask HeroOS.*Included/),
      expect.stringMatching(/Company Blueprint.*Included/),
      expect.stringMatching(/Expert Review.*To be confirmed.*isn't available yet/),
    ]);
    expect(document.body.textContent).not.toMatch(/Full access|Case access|AED|\$|per year|questions|quota|limit|plan/i);
  });

  it("is a reference page, not a dashboard: no numbers, charts, feeds or case lists", () => {
    render(<SpacePage details={details()} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Dashboard|Recent activity|KPI|Explore HR|\d+ (open )?cases/i);
  });

  it("states the Blueprint's completeness and links to it", () => {
    const { unmount } = render(<SpacePage details={details()} />);
    const blueprint = within(screen.getByRole("region", { name: "Company Blueprint" }));
    expect(blueprint.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Company Blueprint" })).toHaveTextContent("Last updated 16 Oct 2026");
    expect(blueprint.getByRole("link", { name: /View Company Blueprint/ })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/settings`);
    unmount();
    render(<SpacePage details={details({ blueprint: { ...BLUEPRINT, industry: null, licensing: { location: "not_sure", authority: null } } })} />);
    const incomplete = within(screen.getByRole("region", { name: "Company Blueprint" }));
    expect(incomplete.getByText("2 details need attention")).toBeInTheDocument();
    expect(incomplete.getByText("Industry, Jurisdiction")).toBeInTheDocument();
    expect(incomplete.getByRole("link", { name: /Review Blueprint/ })).toBeInTheDocument();
    expect(screen.getByText("Jurisdiction not selected")).toBeInTheDocument();
  });

  it("names only who is signed in, and says the rest of the company's people aren't listed yet", () => {
    render(<SpacePage details={details()} />);
    const people = within(screen.getByRole("region", { name: "People" }));
    expect(people.getByText("You")).toBeInTheDocument();
    expect(people.getByText("HeroOS can't list the other people in your company here yet.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/@|Daniel|Mohammed|Layla/);
  });

  it("tells a member what they can and can't use, in words", () => {
    render(<SpacePage details={details({ membership: MEMBER })} />);
    const access = within(screen.getByRole("region", { name: "Your access" }));
    expect(access.getByText("Member")).toBeInTheDocument();
    expect(access.getByText(/Ask HeroOS.*/).closest("li")).toHaveTextContent("Administrators only");
    expect(access.getByText(/^Company Blueprint$/).closest("li")).toHaveTextContent("View only");
  });

  it("makes a short monogram from the company's name", () => {
    expect(monogram("Bush & Bush")).toBe("B&B");
    expect(monogram("Gamma Trading")).toBe("GT");
    expect(monogram("[SYNTHETIC DEMO] Example Trading LLC")).toBe("SDE");
  });
});
