import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Membership, Workspace, WorkspaceDetails } from "@/lib/server/heroos-api";
import { parseCaseSummary } from "@/lib/workflows/model";
import { COMPANY_ID } from "@/test/fixtures";
import { apiCaseSummary, CASE_ID, OTHER_CASE_ID } from "@/test/workflow-fixtures";

import { CompanyShell } from "./company-shell";
import { AdviserMark } from "./workspace-chrome";

const COMPANY_B = "d3e0b000-0000-4000-8000-000000000001";
const ADMIN: Membership = { companyId: COMPANY_ID, membershipId: "m", role: "company_admin", canUpdateBlueprint: true };
const details = (membership: Membership | null = ADMIN): WorkspaceDetails => ({
  company: { id: COMPANY_ID, name: "Gamma Trading" },
  membership,
  blueprint: null,
  cases: [],
});
const ONE: Workspace[] = [{ companyId: COMPANY_ID, name: "Gamma Trading", membershipId: "m", role: "company_admin" }];
const TWO: Workspace[] = [...ONE, { companyId: COMPANY_B, name: "Delta Foods", membershipId: "n", role: "member" }];
const summary = (overrides: Record<string, unknown> = {}) => parseCaseSummary(apiCaseSummary(overrides))!;
const CASES = [summary(), summary({ id: OTHER_CASE_ID, title: "[SYNTHETIC] Other case" })];

function shell({
  cases = CASES as typeof CASES | null,
  workspaces = ONE,
  current,
  initialCasesOpen = false,
  membership = ADMIN as Membership | null,
}: {
  cases?: typeof CASES | null;
  workspaces?: Workspace[];
  current?: "blueprint" | "space";
  initialCasesOpen?: boolean;
  membership?: Membership | null;
} = {}) {
  return render(
    <CompanyShell cases={cases} current={current} details={details(membership)} initialCasesOpen={initialCasesOpen} workspaces={workspaces}>
      <p>Page</p>
    </CompanyShell>,
  );
}

const menuButton = () => screen.getByRole("button", { name: "Account menu: Gamma Trading" });
/** History lists the Company's chats from the BFF: none here, so every case is an earlier record. */
const noChats = () =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ items: [], nextBefore: null }), { status: 200, headers: { "Content-Type": "application/json" } })),
  );

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the workspace header", () => {
  it("has three destinations only: Ask HeroOS (the mark), and the Company Blueprint and Company Space in the account menu", () => {
    shell({ current: "blueprint" });
    const header = within(screen.getByRole("banner"));
    for (const link of header.getAllByRole("link", { name: "HeroOS: ask a new question" })) {
      expect(link).toHaveAttribute("href", `/workspaces/${COMPANY_ID}`);
    }
    fireEvent.click(menuButton());
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");
    const pages = within(header.getByRole("list", { name: "Company" }));
    expect(pages.getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      [expect.stringContaining("Company Blueprint"), `/workspaces/${COMPANY_ID}/settings`],
      [expect.stringContaining("Company Space"), `/workspaces/${COMPANY_ID}/space`],
    ]);
    expect(pages.getByRole("link", { current: "page" })).toHaveTextContent("Company Blueprint");
    // No dashboard, HR Services or "coming soon" navigation, and no permanent sidebar.
    expect(document.body.textContent).not.toMatch(/Dashboard|HR Services|Team & Access|Coming soon/);
    expect(screen.queryByRole("navigation", { name: "Company" })).toBeNull();
    // Signing out is a POST.
    const signOut = header.getByRole("button", { name: "Sign out" });
    expect(signOut.closest("form")).toHaveAttribute("action", "/auth/logout");
    expect(signOut.closest("form")).toHaveAttribute("method", "post");
  });

  it("names the account by the API's answer, never by an invented person", () => {
    shell();
    fireEvent.click(menuButton());
    const header = within(screen.getByRole("banner"));
    expect(header.getByText("Administrator")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Daniel|Haddad/);
  });

  it("closes the account menu with Escape (focus back on its button) or a click elsewhere", async () => {
    shell();
    fireEvent.click(menuButton());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(menuButton()).toHaveFocus());
    fireEvent.click(menuButton());
    fireEvent.pointerDown(screen.getByText("Page"));
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("offers another workspace only when the account has one", () => {
    const { unmount } = shell();
    fireEvent.click(menuButton());
    expect(screen.queryByRole("link", { name: "Switch workspace" })).toBeNull();
    unmount();
    shell({ workspaces: TWO });
    fireEvent.click(menuButton());
    expect(screen.getByRole("link", { name: "Switch workspace" })).toHaveAttribute("href", "/workspaces");
  });

  it("has a History control only for those who can see cases", () => {
    const { unmount } = shell();
    expect(screen.getByRole("button", { name: "History" })).toHaveAttribute("aria-haspopup", "dialog");
    unmount();
    shell({ cases: null, membership: { ...ADMIN, role: "member", canUpdateBlueprint: false } });
    expect(screen.queryByRole("button", { name: "History" })).toBeNull();
  });

  it("opens History from the old case-list links (?cases=open), with earlier case records apart, and closes it with Escape", async () => {
    noChats();
    shell({ initialCasesOpen: true });
    const drawer = await screen.findByRole("dialog", { name: "History" });
    // Chat-first Case: cases with no chat are listed apart and open their case page.
    const records = within(await within(drawer).findByRole("region", { name: "Earlier case records" }));
    expect(records.getAllByRole("link", { name: /SYNTHETIC/ })).toHaveLength(2);
    expect(records.getByRole("link", { name: /Attendance concern/ })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "History" })).toBeNull();
  });

  it("shows the same current HeroOS symbol as HeroOS's own mark in the conversation, never the old logo", () => {
    const { container } = shell();
    const header = container.querySelector("header")!;
    const headerLogos = [...header.querySelectorAll("img")].map((img) => img.getAttribute("src"));
    const { container: turn } = render(<AdviserMark />);
    const conversationLogo = turn.querySelector("img")!.getAttribute("src");
    expect(conversationLogo).toBe("/branding/heroos-symbol.png");
    expect(headerLogos).toContain(conversationLogo);
    expect(headerLogos).not.toContain("/branding/heroos-logo-symbol.png");
  });

  it("starts with the skip link, gives the page one main region and says it's a demonstration environment", () => {
    shell();
    expect(screen.getAllByRole("link")[0]).toHaveTextContent("Skip to content");
    expect(screen.getByRole("main")).toHaveTextContent("Page");
    expect(screen.getByText(/Temporary demonstration environment/)).toBeInTheDocument();
  });
});

