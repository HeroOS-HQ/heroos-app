import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Blueprint } from "@/lib/server/heroos-api";

import { buildPatch, CompanySettingsForm } from "./company-settings-form";

const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";

const BLUEPRINT: Blueprint = {
  companyId: COMPANY_ID,
  legalName: "Gamma Trading FZ-LLC",
  industry: null,
  employeeCount: 12,
  licensing: { location: "difc", authority: null },
  jurisdiction: {
    readiness: "supported_confirmed",
    reason: "confirmed",
    employmentJurisdiction: "difc",
    confirmedAt: "2026-10-14T09:00:00Z",
    guidanceAllowed: true,
  },
  updatedAt: "2026-10-14T09:00:00Z",
};

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup(response: Response | Error = reply(200, { blueprint: { ...BLUEPRINT, industry: "Retail" } }), initial = BLUEPRINT) {
  const fetcher = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  render(<CompanySettingsForm companyId={COMPANY_ID} companyName="Gamma Trading" fetcher={fetcher as unknown as typeof fetch} initial={initial} />);
  return { fetcher };
}

const textbox = (name: RegExp) => screen.getByRole("textbox", { name });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

describe("buildPatch", () => {
  const form = {
    legalName: "Gamma Trading FZ-LLC",
    industry: "",
    employeeCount: "12",
    licensingLocation: "difc" as const,
    licensingAuthority: "",
  };

  it("is empty when nothing changed", () => {
    expect(buildPatch(form, BLUEPRINT)).toEqual({ patch: {}, errors: {} });
  });

  it("contains only changed fields, null for a cleared one", () => {
    expect(buildPatch({ ...form, legalName: " ", industry: "Retail" }, BLUEPRINT).patch).toEqual({
      legal_name: null,
      industry: "Retail",
    });
  });

  it("sends the licensing answer as a whole when it changes", () => {
    expect(buildPatch({ ...form, licensingLocation: "other", licensingAuthority: "X" }, BLUEPRINT).patch).toEqual({
      licensing: { location: "other", authority: "X" },
    });
  });
});

describe("CompanySettingsForm", () => {
  it("prefills the saved values", () => {
    setup();
    expect(textbox(/^Legal business name/)).toHaveValue("Gamma Trading FZ-LLC");
    expect(textbox(/^Number of employees/)).toHaveValue("12");
    expect(screen.getByRole("radio", { name: /^DIFC/ })).toBeChecked();
    expect(screen.getByText("Jurisdiction confirmed: DIFC")).toBeInTheDocument();
  });

  it("saves only the changed field, then shows 'saved' with the API's answer", async () => {
    const { fetcher } = setup();
    fireEvent.change(textbox(/^Industry/), { target: { value: "Retail" } });
    save();

    expect(await screen.findByRole("status")).toHaveTextContent("Changes saved");
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/blueprint`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ industry: "Retail" });
    expect(textbox(/^Industry/)).toHaveValue("Retail");
  });

  it("does not call the server when nothing changed", async () => {
    const { fetcher } = setup();
    save();
    expect(await screen.findByRole("status")).toHaveTextContent("No changes to save");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("warns that changing the licensing answer withdraws the confirmation, and clears a stale authority", () => {
    setup();
    fireEvent.click(screen.getByRole("radio", { name: /^Other/ }));
    expect(screen.getByText("Your jurisdiction will need to be confirmed again")).toBeInTheDocument();
    fireEvent.change(textbox(/^Which authority/), { target: { value: "Example Authority" } });
    fireEvent.click(screen.getByRole("radio", { name: /^I'm not sure/ }));
    fireEvent.click(screen.getByRole("radio", { name: /^Other/ }));
    expect(textbox(/^Which authority/)).toHaveValue("");
  });

  it.each([
    [reply(403, { error: "refused" }), "You can't change these details"],
    [reply(401, { error: "session_expired" }), "Your session has ended"],
    [reply(422, { error: "invalid", fields: ["industry"] }), "Some details need attention"],
    [reply(503, { error: "unavailable" }), "We couldn't save your changes"],
    [new TypeError("Failed to fetch"), "We couldn't save your changes"],
    [reply(200, { blueprint: { ...BLUEPRINT, companyId: "d3e0b000-0000-4000-8000-000000000001" } }), "We couldn't save your changes"],
  ])("never shows 'saved' after a failure (%#)", async (response, title) => {
    setup(response);
    fireEvent.change(textbox(/^Industry/), { target: { value: "Retail" } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(title);
    expect(screen.queryByText("Changes saved")).toBeNull();
    // The unsaved edit is kept.
    expect(textbox(/^Industry/)).toHaveValue("Retail");
  });

  it("validates before sending", async () => {
    const { fetcher } = setup();
    fireEvent.change(textbox(/^Number of employees/), { target: { value: "-3" } });
    save();
    await waitFor(() => expect(textbox(/^Number of employees/)).toHaveAttribute("aria-invalid", "true"));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("shows the company name read-only (there is no rename)", () => {
    setup();
    expect(screen.queryByRole("textbox", { name: /^Company name/ })).toBeNull();
    const details = screen.getByRole("region", { name: "Company details" });
    expect(within(details).getByText("Gamma Trading")).toBeInTheDocument();
  });
});
