import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { attentionOf, type BlueprintForm, buildPatch, formFrom, jurisdictionDisplay } from "@/lib/blueprint/model";
import type { Blueprint, BlueprintPerson } from "@/lib/server/heroos-api";

import { BlueprintPage } from "./blueprint-page";

const COMPANY_ID = "d3e0a000-0000-4000-8000-000000000001";

const ME = "d3e0a000-0000-4000-8000-00000000a001";
const COLLEAGUE = "d3e0a000-0000-4000-8000-00000000a002";

/** A Blueprint from an API before M2-NEW-03: profile and jurisdiction only. */
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
  version: "legacy",
  websiteUrl: null,
  companySummary: null,
  policiesExist: null,
  policyContext: null,
  hrSupport: null,
  hrSupportNotes: null,
  primaryContact: null,
  people: [],
  missing: null,
};

const YOU: BlueprintPerson = {
  membershipId: ME,
  role: "company_admin",
  memberSince: "2026-10-13T08:00:00Z",
  isCurrentUser: true,
  isPrimaryContact: true,
};
const OTHER: BlueprintPerson = {
  membershipId: COLLEAGUE,
  role: "member",
  memberSince: "2026-10-19T08:00:00Z",
  isCurrentUser: false,
  isPrimaryContact: false,
};

/** The full company context (M2-NEW-03). */
const CONTEXT: Blueprint = {
  ...BLUEPRINT,
  industry: "Retail",
  version: "context",
  websiteUrl: "https://gamma.example",
  companySummary: "Two shops in Dubai.\n\nA store manager leads eight staff.",
  policiesExist: "yes",
  policyContext: "Employee handbook",
  hrSupport: "external",
  hrSupportNotes: null,
  primaryContact: YOU,
  people: [YOU, OTHER],
  missing: [],
  updatedAt: "2026-10-21T10:05:00Z",
};

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function setup({
  response = reply(200, { blueprint: { ...BLUEPRINT, industry: "Retail" } }),
  initial = BLUEPRINT,
  editable = true,
}: { response?: Response | Error; initial?: Blueprint; editable?: boolean } = {}) {
  const fetcher = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  render(
    <BlueprintPage
      companyId={COMPANY_ID}
      companyName="Gamma Trading"
      editable={editable}
      fetcher={fetcher as unknown as typeof fetch}
      initial={initial}
    />,
  );
  return { fetcher };
}

const edit = () => fireEvent.click(screen.getByRole("button", { name: "Edit Blueprint" }));
const textbox = (name: RegExp) => screen.getByRole("textbox", { name });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

describe("buildPatch", () => {
  const form: BlueprintForm = formFrom(BLUEPRINT);

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

  it("never sends company context to an API that doesn't keep it", () => {
    expect(buildPatch({ ...form, websiteUrl: "gamma.example", hrSupport: "none" }, BLUEPRINT).patch).toEqual({});
  });

  it("sends the context exactly as the API stores it: the website normalized, pasted text tidied", () => {
    const context = formFrom(CONTEXT);
    expect(
      buildPatch(
        {
          ...context,
          websiteUrl: " WWW.Gamma.example/ ",
          companySummary: "Two shops.\r\n\r\nEight\u00a0staff. ",
          policiesExist: "not_sure",
          hrSupport: "mixed",
          hrSupportNotes: "A consultant helps us.",
          primaryContact: COLLEAGUE,
        },
        CONTEXT,
      ),
    ).toEqual({
      errors: {},
      patch: {
        website_url: "https://www.gamma.example",
        company_summary: "Two shops.\n\nEight staff.",
        policies_exist: "not_sure",
        hr_support: "mixed",
        hr_support_notes: "A consultant helps us.",
        primary_contact_membership_id: COLLEAGUE,
      },
    });
  });

  it("refuses unsafe websites and overlong text before anything is sent", () => {
    const context = formFrom(CONTEXT);
    expect(buildPatch({ ...context, websiteUrl: "javascript:alert(1)" }, CONTEXT).errors).toEqual({
      websiteUrl: "Use a web address that starts with https:// or http://.",
    });
    expect(buildPatch({ ...context, companySummary: "x".repeat(2001) }, CONTEXT).errors).toEqual({
      companySummary: "Use 2,000 characters or fewer.",
    });
    expect(buildPatch({ ...context, policyContext: "x".repeat(1001), hrSupportNotes: "y".repeat(501) }, CONTEXT).errors).toEqual({
      policyContext: "Use 1,000 characters or fewer.",
      hrSupportNotes: "Use 500 characters or fewer.",
    });
  });
});

describe("the jurisdiction as the Blueprint shows it", () => {
  it("names the confirmed jurisdiction plainly, and the founder's answer until one is confirmed", () => {
    expect(jurisdictionDisplay(BLUEPRINT)).toEqual({ kind: "set", label: "DIFC", detail: "Dubai International Financial Centre", note: null });
    const other: Blueprint = {
      ...BLUEPRINT,
      licensing: { location: "other", authority: "Example Free Zone Authority" },
      jurisdiction: { ...BLUEPRINT.jurisdiction, readiness: "unconfirmed", reason: "awaiting_confirmation", employmentJurisdiction: null, guidanceAllowed: false },
    };
    const shown = jurisdictionDisplay(other);
    expect(shown).toMatchObject({ kind: "set", label: "Example Free Zone Authority", detail: "Licensed by Example Free Zone Authority" });
    expect(shown.kind === "set" && shown.note).toMatch(/waiting to be confirmed/);
    expect(jurisdictionDisplay({ ...BLUEPRINT, licensing: { location: "not_sure", authority: null } }).kind).toBe("missing");
  });

  it("uses the API's completeness when it has one, in the page's words", () => {
    expect(attentionOf(CONTEXT)).toEqual([]);
    const incomplete: Blueprint = {
      ...CONTEXT,
      licensing: { location: "other", authority: null },
      missing: ["company_summary", "jurisdiction", "policies", "hr_support", "primary_contact"],
    };
    expect(attentionOf(incomplete)).toEqual([
      { field: "companySummary", label: "Company summary" },
      // "Another jurisdiction" without its authority: the authority is what's missing.
      { field: "licensingAuthority", label: "Licensing authority" },
      { field: "policiesExist", label: "HR policies" },
      { field: "hrSupport", label: "HR support" },
      { field: "primaryContact", label: "Primary contact" },
    ]);
  });

  it("counts only the details a legacy API keeps as needing attention", () => {
    expect(attentionOf(BLUEPRINT).map((item) => item.label)).toEqual(["Industry"]);
    const empty: Blueprint = { ...BLUEPRINT, legalName: null, employeeCount: null, licensing: { location: null, authority: null } };
    expect(attentionOf(empty).map((item) => item.label)).toEqual(["Legal company name", "Industry", "Number of employees", "Jurisdiction"]);
  });
});

describe("BlueprintPage against an API without the company context", () => {
  it("reads first: the company's details from the API, the jurisdiction without a 'confirmed' badge", () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "Company Blueprint" })).toBeInTheDocument();
    expect(screen.getByText("HeroOS uses this information to tailor HR guidance to Gamma Trading.")).toBeInTheDocument();
    const basics = within(screen.getByRole("region", { name: "Company basics" }));
    expect(basics.getByText("Gamma Trading")).toBeInTheDocument();
    expect(basics.getByText("Gamma Trading FZ-LLC")).toBeInTheDocument();
    expect(basics.getByText("Number of employees").nextElementSibling).toHaveTextContent("12");
    expect(basics.getByText("Industry").nextElementSibling).toHaveTextContent("Not added");
    const jurisdiction = within(screen.getByRole("region", { name: "Jurisdiction" }));
    expect(jurisdiction.getByText("DIFC")).toBeInTheDocument();
    expect(jurisdiction.getByText("Dubai International Financial Centre")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Confirmed|verified|compliant/);
    // Completeness is one quiet line, never a score.
    expect(screen.getByText("1 detail needs attention")).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toHaveTextContent("Last updated 14 Oct 2026, 09:00 UTC");
    // No fields the API doesn't keep yet, and no form until Edit.
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByText(/policies added|HR support:|Primary contact/i)).toBeNull();
    expect(screen.getByText(/Coming next to the Blueprint/)).toBeInTheDocument();
  });

  it("has one Edit for everything; Done leaves without saving when nothing changed", () => {
    const { fetcher } = setup();
    edit();
    expect(screen.getByText("Editing")).toBeInTheDocument();
    expect(textbox(/^Legal company name/)).toHaveValue("Gamma Trading FZ-LLC");
    expect(textbox(/^Number of employees/)).toHaveValue("12");
    expect(screen.getByRole("radio", { name: /^DIFC/ })).toBeChecked();
    // The workspace name isn't editable here.
    expect(screen.queryByRole("textbox", { name: /^Company name/ })).toBeNull();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("marks what changed, saves only that, and confirms it with the API's answer", async () => {
    const { fetcher } = setup();
    edit();
    fireEvent.change(textbox(/^Industry/), { target: { value: "Retail" } });
    const bar = within(screen.getByRole("region", { name: "Unsaved changes" }));
    expect(bar.getByText("1 unsaved change")).toBeInTheDocument();
    expect(bar.getByText(/Industry/)).toBeInTheDocument();
    expect(screen.getByText("Edited")).toBeInTheDocument();
    save();

    const confirmation = await screen.findByRole("status");
    expect(confirmation).toHaveTextContent("Company Blueprint updated");
    expect(confirmation).toHaveTextContent("Industry saved.");
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/blueprint`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ industry: "Retail" });
    // Back to reading, with the saved value and the change marked.
    const basics = within(screen.getByRole("region", { name: "Company basics" }));
    expect(basics.getByText("Retail")).toBeInTheDocument();
    expect(basics.getByText("Updated")).toBeInTheDocument();
    expect(screen.getByText("Blueprint complete")).toBeInTheDocument();
  });

  it("discards an edit without calling the server", () => {
    const { fetcher } = setup();
    edit();
    fireEvent.change(textbox(/^Industry/), { target: { value: "Retail" } });
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("region", { name: "Company basics" })).toHaveTextContent(/IndustryNot added/);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("asks for the authority with another jurisdiction, and drops it when the answer changes", () => {
    setup();
    edit();
    fireEvent.click(screen.getByRole("radio", { name: /^Another jurisdiction/ }));
    fireEvent.change(textbox(/^Licensing authority/), { target: { value: "Example Authority" } });
    fireEvent.click(screen.getByRole("radio", { name: /^Not sure yet/ }));
    fireEvent.click(screen.getByRole("radio", { name: /^Another jurisdiction/ }));
    expect(textbox(/^Licensing authority/)).toHaveValue("");
    expect(screen.getByText(/jurisdiction-specific guidance may be unavailable until the new setting is in place/)).toBeInTheDocument();
  });

  it.each([
    [reply(403, { error: "refused" }), "Only company administrators can edit the Blueprint"],
    [reply(401, { error: "session_expired" }), "Your session has ended"],
    [reply(422, { error: "invalid", fields: ["industry"] }), "Check the highlighted details"],
    [reply(503, { error: "unavailable" }), "HeroOS didn't confirm the update"],
    [new TypeError("Failed to fetch"), "HeroOS didn't confirm the update"],
    [reply(200, { blueprint: { ...BLUEPRINT, companyId: "d3e0b000-0000-4000-8000-000000000001" } }), "HeroOS didn't confirm the update"],
  ])("never says 'updated' after a failure, and keeps the edit (%#)", async (response, text) => {
    setup({ response });
    edit();
    fireEvent.change(textbox(/^Industry/), { target: { value: "Retail" } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByText("Company Blueprint updated")).toBeNull();
    expect(textbox(/^Industry/)).toHaveValue("Retail");
  });

  it("validates before sending", async () => {
    const { fetcher } = setup();
    edit();
    fireEvent.change(textbox(/^Number of employees/), { target: { value: "-3" } });
    save();
    await waitFor(() => expect(textbox(/^Number of employees/)).toHaveAttribute("aria-invalid", "true"));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("lists what needs attention, and each item opens the editor at that detail", async () => {
    setup({ initial: { ...BLUEPRINT, legalName: null, licensing: { location: "not_sure", authority: null } } });
    expect(screen.getByText("3 details need attention")).toBeInTheDocument();
    const attention = within(screen.getByRole("navigation", { name: "Details that need attention" }));
    fireEvent.click(attention.getByRole("button", { name: /Industry/ }));
    expect(screen.getByText("Editing")).toBeInTheDocument();
    await waitFor(() => expect(textbox(/^Industry/)).toHaveFocus());
    // The read view's missing jurisdiction says what it affects.
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    const jurisdiction = within(screen.getByRole("region", { name: "Jurisdiction" }));
    expect(jurisdiction.getByText("Jurisdiction not selected")).toBeInTheDocument();
    expect(jurisdiction.getByText(/HeroOS can't give jurisdiction-specific guidance/)).toBeInTheDocument();
  });

  it("gives someone who can't update the Blueprint a read-only page", () => {
    setup({ editable: false, initial: { ...BLUEPRINT, legalName: null } });
    expect(screen.queryByRole("button", { name: "Edit Blueprint" })).toBeNull();
    // What needs attention is named, without a way into an editor they can't use.
    const attention = within(screen.getByRole("navigation", { name: "Details that need attention" }));
    expect(attention.queryAllByRole("button")).toHaveLength(0);
    expect(attention.getByText("Industry")).toBeInTheDocument();
    // No roles or permissions on this page.
    expect(document.body.textContent).not.toMatch(/administrator|permission/i);
  });
});

describe("BlueprintPage with the company context (M2-NEW-03)", () => {
  const contextReply = (changes: Partial<Blueprint>) => reply(200, { blueprint: { ...CONTEXT, ...changes } });
  const region = (name: string) => within(screen.getByRole("region", { name }));

  it("shows every detail the API keeps, quietly, with nothing it doesn't", () => {
    setup({ initial: CONTEXT });
    const basics = region("Company basics");
    const link = basics.getByRole("link", { name: "https://gamma.example" });
    expect(link).toHaveAttribute("href", "https://gamma.example");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    // Paragraph breaks kept, rendered as text (never HTML).
    const summary = basics.getByText(/Two shops in Dubai\./);
    expect(summary.textContent).toBe("Two shops in Dubai.\n\nA store manager leads eight staff.");
    expect(summary).toHaveClass("whitespace-pre-line");
    expect(region("Policies").getByText("Yes, the company has HR policies")).toBeInTheDocument();
    expect(region("Policies").getByText("Employee handbook")).toBeInTheDocument();
    expect(region("Policies").getByText("Uploading policy documents isn't available yet.")).toBeInTheDocument();
    expect(region("HR support").getByText("An outside provider")).toBeInTheDocument();
    const people = region("People");
    expect(people.getByText("Primary contact").nextElementSibling).toHaveTextContent(/^You$/);
    expect(people.getByText("Others with access").nextElementSibling).toHaveTextContent("Another person · joined 19 Oct 2026");
    expect(screen.getByText("Blueprint complete")).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toHaveTextContent("Last updated 21 Oct 2026, 10:05 UTC");
    expect(screen.queryByText(/Coming next/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/administrator|permission|Confirmed|compliant/i);
  });

  it("never renders text as HTML", () => {
    setup({ initial: { ...CONTEXT, companySummary: "<img src=x onerror=alert(1)> <b>bold</b>" } });
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(region("Company basics").getByText("<img src=x onerror=alert(1)> <b>bold</b>")).toBeInTheDocument();
  });

  it("tells the primary contact and the person signed in apart", () => {
    setup({ initial: { ...CONTEXT, primaryContact: { ...OTHER, isPrimaryContact: true }, people: [{ ...YOU, isPrimaryContact: false }, { ...OTHER, isPrimaryContact: true }] } });
    const people = region("People");
    expect(people.getByText("Primary contact").nextElementSibling).toHaveTextContent("Another person · joined 19 Oct 2026");
    expect(people.getByText("Signed in as").nextElementSibling).toHaveTextContent(/^You$/);
  });

  it("edits the context with the summary's guidance and saves exactly the changes", async () => {
    const saved = {
      companySummary: "We run two shops.",
      websiteUrl: "https://www.gamma.example",
      hrSupport: "mixed" as const,
      primaryContact: { ...OTHER, isPrimaryContact: true },
      people: [{ ...YOU, isPrimaryContact: false }, { ...OTHER, isPrimaryContact: true }],
    };
    const { fetcher } = setup({ initial: CONTEXT, response: contextReply(saved) });
    edit();
    expect(
      screen.getByText(
        "Briefly describe what your company does and how your team is structured. You can paste or adapt content from your website or About page.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("HeroOS keeps the address only. It doesn't visit or read your website.")).toBeInTheDocument();
    fireEvent.change(textbox(/^Company website/), { target: { value: "www.Gamma.example" } });
    fireEvent.change(textbox(/^Company summary/), { target: { value: "We run two shops. " } });
    fireEvent.click(screen.getByRole("radio", { name: /^Both/ }));
    const contact = screen.getByRole("combobox", { name: /^Primary contact/ });
    expect([...(contact as HTMLSelectElement).options].map((option) => option.text)).toEqual(["You", "Another person · joined 19 Oct 2026"]);
    fireEvent.change(contact, { target: { value: COLLEAGUE } });
    const bar = within(screen.getByRole("region", { name: "Unsaved changes" }));
    expect(bar.getByText("4 unsaved changes")).toBeInTheDocument();
    save();

    const confirmation = await screen.findByRole("status");
    expect(confirmation).toHaveTextContent("Company Blueprint updated");
    expect(confirmation).toHaveTextContent("Company website, Company summary, HR support, Primary contact saved.");
    const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      website_url: "https://www.gamma.example",
      company_summary: "We run two shops.",
      hr_support: "mixed",
      primary_contact_membership_id: COLLEAGUE,
    });
    expect(region("Company basics").getByText("We run two shops.")).toBeInTheDocument();
    expect(region("People").getByText("Primary contact").nextElementSibling).toHaveTextContent("Another person");
  });

  it("refuses an unsafe website next to the field without sending anything", async () => {
    const { fetcher } = setup({ initial: CONTEXT });
    edit();
    fireEvent.change(textbox(/^Company website/), { target: { value: "javascript:alert(1)" } });
    save();
    await waitFor(() => expect(textbox(/^Company website/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Use a web address that starts with https:// or http://.")).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("names what needs attention and opens the editor at it", async () => {
    setup({
      initial: { ...CONTEXT, companySummary: null, hrSupport: null, primaryContact: null, missing: ["company_summary", "hr_support", "primary_contact"] },
    });
    expect(screen.getByText("3 details need attention")).toBeInTheDocument();
    expect(region("People").getByText("Not chosen yet")).toBeInTheDocument();
    const attention = within(screen.getByRole("navigation", { name: "Details that need attention" }));
    expect(attention.getAllByRole("button").map((button) => button.textContent)).toEqual(["Company summary", "HR support", "Primary contact"]);
    fireEvent.click(attention.getByRole("button", { name: /Primary contact/ }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: /^Primary contact/ })).toHaveFocus());
    expect(screen.getByRole("option", { name: "Choose the primary contact" })).toBeDisabled();
  });

  it("shows the API's refusal of a primary contact next to it", async () => {
    setup({ initial: CONTEXT, response: reply(422, { error: "invalid", fields: ["primaryContact"] }) });
    edit();
    fireEvent.change(screen.getByRole("combobox", { name: /^Primary contact/ }), { target: { value: COLLEAGUE } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent("Check the highlighted details");
    expect(screen.getByRole("combobox", { name: /^Primary contact/ })).toHaveAttribute("aria-invalid", "true");
  });
});
