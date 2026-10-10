import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompanyWorkspace } from "./company-workspace";

describe("CompanyWorkspace", () => {
  it("offers sign-in as a plain link to the login route", () => {
    render(<CompanyWorkspace view={{ kind: "signed_out", authOutcome: null }} />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/auth/login");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    ["failed", "Sign-in could not be completed. Please try again."],
    ["cancelled", "Sign-in was cancelled."],
    ["expired", "The sign-in attempt expired. Please try again."],
  ])("shows a fixed message for the %s outcome", (outcome, message) => {
    render(<CompanyWorkspace view={{ kind: "signed_out", authOutcome: outcome }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("ignores unknown outcome values instead of rendering them", () => {
    const { container } = render(
      <CompanyWorkspace view={{ kind: "signed_out", authOutcome: "<img src=x onerror=alert(1)>" }} />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("lists the company's cases and signs out with a POST form", () => {
    const { container } = render(
      <CompanyWorkspace
        view={{
          kind: "signed_in",
          company: { id: "c", name: "[SYNTHETIC DEMO] Alpha Example Co." },
          cases: [{ id: "1", title: "[SYNTHETIC DEMO] Case A-1", caseType: "general", createdAt: "x" }],
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "[SYNTHETIC DEMO] Alpha Example Co." })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Cases" })).toHaveTextContent("[SYNTHETIC DEMO] Case A-1");
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/auth/logout");
    expect(form).toHaveAttribute("method", "post");
  });

  it.each([
    ["unauthenticated", "Your session has expired. Please sign in again.", "Sign in"],
    ["forbidden", "Your account does not have access to the demo company.", "Sign out"],
    ["unavailable", "The HeroOS service is temporarily unavailable. Please try again later.", "Sign out"],
  ] as const)("maps the %s API failure to a fixed message", (failure, message, action) => {
    render(<CompanyWorkspace view={{ kind: "error", failure }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText(action)).toBeInTheDocument();
  });

  it("explains when sign-in is not configured", () => {
    render(<CompanyWorkspace view={{ kind: "not_configured" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Sign-in is not configured");
  });
});
