import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fromApiDocumentsList, fromApiPreview, fromApiTemplateForm } from "@/lib/documents/model";
import {
  apiDocuments,
  apiForm,
  apiNotInstalled,
  apiPreview,
  apiSummary,
  HOSTILE,
  NAME,
  TEMPLATE_KEY,
  unavailableSummary,
} from "@/test/document-fixtures";
import { COMPANY_ID } from "@/test/fixtures";
import { apiProgression, CASE_ID, view } from "@/test/workflow-fixtures";

import { CaseWorkspace } from "./case-workspace";
import { DocumentsPanel } from "./documents-panel";

const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
// What the BFF returns: the server-parsed (camelCase) shapes.
const documents = (body: unknown = apiDocuments()) => reply(200, { documents: fromApiDocumentsList(body) });
const form = () => reply(200, { form: fromApiTemplateForm(apiForm()) });
const preview = (values?: string[]) => reply(200, { preview: fromApiPreview(apiPreview(values)) });

function fetcherOf(...responses: (Response | Error)[]) {
  const queue = [...responses];
  return vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
}

const panel = (fetcher: ReturnType<typeof fetcherOf>, revision = 5) =>
  render(<DocumentsPanel caseId={CASE_ID} companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} revision={revision} />);

async function openForm(fetcher: ReturnType<typeof fetcherOf>) {
  panel(fetcher);
  fireEvent.click(await screen.findByRole("button", { name: /Open/ }));
  return screen.findByRole("heading", { name: "Synthetic test letter: check-in note" });
}

const previewRegion = () => within(screen.getByRole("article"));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DocumentsPanel (M2-04C)", () => {
  it("lists what can be previewed now and why the rest can't", async () => {
    const fetcher = fetcherOf(
      documents(
        apiDocuments([
          apiSummary(),
          unavailableSummary("not_at_this_stage", "Offered at another stage of this case."),
          unavailableSummary("specialist_review_required", "Needs a specialist's review first.", {
            key: "synthetic.specialist_letter",
            code: "TEST-03",
          }),
        ]),
      ),
    );
    panel(fetcher);
    expect(await screen.findByRole("button", { name: /Open.*check-in note/ })).toBeTruthy();
    expect(screen.getByText("Synthetic test templates")).toBeTruthy();
    expect(screen.getByText("Template wording here is provisional: not approved for use.")).toBeTruthy();
    expect(screen.getByText("Not available now (2)")).toBeTruthy();
    expect(screen.getByText("Offered at another stage of this case.")).toBeTruthy();
    expect(screen.getByText("Needs a specialist's review first.")).toBeTruthy();
    // Only the available template can be opened.
    expect(screen.getAllByRole("button", { name: /Open/ })).toHaveLength(1);
    const { url, init } = { url: fetcher.mock.calls[0][0], init: fetcher.mock.calls[0][1] };
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/documents`);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("says when no templates are installed, or the API doesn't offer documents yet", async () => {
    panel(fetcherOf(documents(apiNotInstalled())));
    expect(await screen.findByText("Document templates aren't available in this environment.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Open/ })).toBeNull();
  });

  it("treats an API without document routes as not available yet", async () => {
    panel(fetcherOf(reply(404, { error: "not_found" })));
    expect(await screen.findByText("Documents aren't available yet")).toBeTruthy();
  });

  it("reads the list again when the case changes", async () => {
    const fetcher = fetcherOf(
      documents(apiDocuments([unavailableSummary("not_at_this_stage", "Offered at another stage of this case.")])),
      documents(),
    );
    const { rerender } = panel(fetcher, 5);
    expect(await screen.findByText("No template can be previewed at this point of the case.")).toBeTruthy();
    rerender(<DocumentsPanel caseId={CASE_ID} companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} revision={6} />);
    expect(await screen.findByRole("button", { name: /Open/ })).toBeTruthy();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("opens the form with the case's suggestion, instructions and the privacy notice", async () => {
    const fetcher = fetcherOf(documents(), form());
    await openForm(fetcher);
    expect(fetcher.mock.calls[1][0]).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/documents/${TEMPLATE_KEY}`);
    expect((screen.getByRole("textbox", { name: "Recipient's name" }) as HTMLInputElement).value).toBe(NAME);
    expect(screen.getByText("Suggested from this case. You can change or clear it.", { exact: false })).toBeTruthy();
    expect(screen.getByText("Instructions for you (not part of the document)")).toBeTruthy();
    expect(screen.getAllByText(/Nothing you type here is saved, sent or kept/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Leave out health, family, religion/).length).toBe(2);
    // The browser isn't asked to remember any of it.
    expect(screen.getByRole("form").getAttribute("autocomplete")).toBe("off");
    for (const field of screen.getAllByRole("textbox")) expect(field.getAttribute("autocomplete")).toBe("off");
  });

  it("checks the details before asking for a preview", async () => {
    const fetcher = fetcherOf(documents(), form());
    await openForm(fetcher);
    fireEvent.change(screen.getByRole("textbox", { name: "Recipient's name" }), { target: { value: "Sam​Example" } });
    fireEvent.click(screen.getByRole("button", { name: "Show preview" }));
    expect(await screen.findByText("Some details need attention")).toBeTruthy();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shows the preview as text with a watermark, gaps and nothing executable", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetcher = fetcherOf(documents(), form(), preview(HOSTILE));
    await openForm(fetcher);
    fireEvent.change(screen.getByRole("textbox", { name: "Points discussed, entry 1" }), { target: { value: " [SYNTHETIC] Arrival times " } });
    fireEvent.click(screen.getByLabelText("Online"));
    fireEvent.click(screen.getByRole("button", { name: "Show preview" }));

    await screen.findByRole("article");
    const sent = JSON.parse(String(fetcher.mock.calls[2][1]?.body)) as Record<string, unknown>;
    expect(fetcher.mock.calls[2][0]).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/documents/${TEMPLATE_KEY}/preview`);
    expect(fetcher.mock.calls[2][1]?.method).toBe("POST");
    expect(sent).toEqual({
      templateVersion: 1,
      values: { recipient_name: NAME, discussion_points: ["[SYNTHETIC] Arrival times"] },
      choices: { meeting_format: ["online"] },
    });

    const region = previewRegion();
    for (const value of HOSTILE) expect(region.getByText(value)).toBeTruthy();
    const article = screen.getByRole("article");
    // Text only: nothing became an element, a link or a script.
    expect(article.querySelectorAll("script, img, a, iframe, object, embed, form")).toHaveLength(0);
    expect(article.querySelectorAll("[data-watermark]")).toHaveLength(3);
    expect(region.getAllByText("Preview — not issued").length).toBeGreaterThanOrEqual(2);
    expect(region.getByText("Template wording: provisional, not approved for use.")).toBeTruthy();
    expect(region.getByText("[Short summary: not provided]")).toBeTruthy();
    expect(region.getByText("1 detail isn't provided yet: it shows as a gap below.")).toBeTruthy();
    expect(region.getByText("Signature:")).toBeTruthy();
    // No way to download, send or issue it, and nothing kept in the browser.
    expect(screen.queryByRole("button", { name: /download|send|issue|save/i })).toBeNull();
    expect(setItem).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Update preview" })).toBeTruthy();
  });

  it("names the fields the API refused and explains a conflict", async () => {
    const fetcher = fetcherOf(
      documents(),
      form(),
      reply(422, { error: "invalid", fields: ["recipient_name"] }),
      reply(409, { error: "conflict" }),
    );
    await openForm(fetcher);
    fireEvent.click(screen.getByRole("button", { name: "Show preview" }));
    expect(await screen.findByText("Some details need attention")).toBeTruthy();
    const name = screen.getByRole("textbox", { name: "Recipient's name" });
    expect(name.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("HeroOS couldn't accept this. Check it and try again.")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Recipient's name" }), { target: { value: "[SYNTHETIC] Alex" } });
    fireEvent.click(screen.getByRole("button", { name: "Show preview" }));
    expect(await screen.findByText("This template can't be previewed now")).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("forgets everything typed when the form is closed", async () => {
    const fetcher = fetcherOf(documents(), form(), form());
    await openForm(fetcher);
    fireEvent.change(screen.getByRole("textbox", { name: "Recipient's name" }), { target: { value: "[SYNTHETIC] Typed" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(await screen.findByRole("button", { name: /Open/ }));
    await screen.findByRole("heading", { name: "Synthetic test letter: check-in note" });
    expect((screen.getByRole("textbox", { name: "Recipient's name" }) as HTMLInputElement).value).toBe(NAME);
  });
});

describe("the Documents section in the case workspace", () => {
  const workspace = (overrides: Parameters<typeof view>[0], documentsFetcher: ReturnType<typeof fetcherOf>) =>
    render(
      <CaseWorkspace
        cases={[]}
        companyId={COMPANY_ID}
        documentsFetcher={documentsFetcher as unknown as typeof fetch}
        initialView={view({ company: "uae_federal", revision: 5, progression: apiProgression(), ...overrides })}
      />,
    );

  it("appears for administrators, with a link from the header", async () => {
    workspace({}, fetcherOf(documents()));
    expect(await screen.findByRole("region", { name: "Documents" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Documents" }).getAttribute("href")).toBe("#documents");
    await waitFor(() => expect(screen.getByRole("button", { name: /Open.*check-in note/ })).toBeTruthy());
  });

  it("isn't offered to anyone who can't edit the case", () => {
    const fetcher = fetcherOf(documents());
    workspace({ canEdit: false }, fetcher);
    expect(screen.queryByRole("region", { name: "Documents" })).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
