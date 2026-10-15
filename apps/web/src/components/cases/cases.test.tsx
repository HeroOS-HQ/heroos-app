import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseCaseSummary } from "@/lib/workflows/model";
import { COMPANY_ID } from "@/test/fixtures";
import {
  ALL_CLEAR,
  apiCaseSummary,
  CASE_ID,
  HIGH_RISK_HOLD,
  NARRATIVE,
  OTHER_CASE_ID,
  POLICY_CAUTION,
  view,
} from "@/test/workflow-fixtures";

import { CasesDashboard } from "./cases-dashboard";
import { CaseWorkspace } from "./case-workspace";
import { NewCaseForm } from "./new-case-form";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function fetcherOf(...responses: (Response | Error)[]) {
  const queue = [...responses];
  return vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => {
    const next = queue.shift() ?? new Error("no response queued");
    if (next instanceof Error) throw next;
    return next;
  });
}

const bodyOf = (fetcher: ReturnType<typeof fetcherOf>, call = 0) =>
  JSON.parse(String((fetcher.mock.calls[call] as [string, RequestInit])[1].body)) as Record<string, unknown>;

const summary = (overrides: Record<string, unknown> = {}) => parseCaseSummary(apiCaseSummary(overrides))!;

describe("CasesDashboard", () => {
  it("lists the Company's cases with their status in words and a New case action for administrators", () => {
    render(
      <CasesDashboard
        cases={[
          summary({ status: { code: "intake_in_progress", label: "Intake in progress" }, answered: 3, total: 10 }),
          summary({ id: OTHER_CASE_ID, title: "[SYNTHETIC] Second", status: { code: "held_for_specialist_review", label: "On hold: specialist review needed" }, answered: 19, total: 19 }),
        ]}
        companyId={COMPANY_ID}
        companyName="[SYNTHETIC] Alpha"
      />,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Disciplinary cases");
    expect(screen.getByRole("link", { name: "New case" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/new`);
    const list = screen.getByRole("list", { name: "Disciplinary cases" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`,
      `/workspaces/${COMPANY_ID}/cases/${OTHER_CASE_ID}`,
    ]);
    expect(links[0]).toHaveTextContent("3 of 10 intake questions answered");
    expect(links[0]).toHaveTextContent("Last updated 15 Oct 2026");
    expect(links[1]).toHaveTextContent("On hold: specialist review needed");
    // The slice says what it does not do.
    expect(screen.getByText("Early version: intake only")).toBeInTheDocument();
  });

  it("explains the empty state and that cases are confidential to administrators", () => {
    render(<CasesDashboard cases={[]} companyId={COMPANY_ID} companyName="A" />);
    expect(screen.getByRole("heading", { name: "No Disciplinary cases yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a case" })).toBeInTheDocument();
    expect(screen.getByText(/only your company's administrators can see them/)).toBeInTheDocument();
  });
});

describe("NewCaseForm", () => {
  const titleBox = () => screen.getByRole("textbox", { name: /Case title/ });
  const submit = () => fireEvent.click(screen.getByRole("button", { name: /Create case/ }));

  it("requires a title before calling anything", () => {
    const fetcher = fetcherOf();
    render(<NewCaseForm companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} />);
    submit();
    expect(screen.getByText("Please give the case a short title.")).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("creates the case once, even when submitted twice, and opens it", async () => {
    const fetcher = fetcherOf(reply(200, { case: summary() }));
    const navigate = vi.fn();
    render(<NewCaseForm companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} navigate={navigate} />);
    fireEvent.change(titleBox(), { target: { value: "  [SYNTHETIC] Attendance concern " } });
    // A double click: the same button twice, the second while the first request runs.
    const button = screen.getByRole("button", { name: /Create case/ });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/workspaces/${COMPANY_ID}/cases/${CASE_ID}`));
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url] = fetcher.mock.calls[0] as [string];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/workflows/disciplinary/cases`);
    const body = bodyOf(fetcher);
    expect(body.title).toBe("[SYNTHETIC] Attendance concern");
    expect(body.requestKey).toMatch(UUID);
    expect(Object.keys(body).sort()).toEqual(["requestKey", "title"]);
  });

  it("retries a lost request with the same key, and a new title with a new key", async () => {
    const fetcher = fetcherOf(new TypeError("network"), reply(503, { error: "unavailable" }), reply(200, { case: summary() }));
    render(<NewCaseForm companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} navigate={vi.fn()} />);
    fireEvent.change(titleBox(), { target: { value: "Attendance" } });
    submit();
    await screen.findByText(/won't be created twice/);
    submit();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(bodyOf(fetcher, 1).requestKey).toBe(bodyOf(fetcher, 0).requestKey);

    fireEvent.change(titleBox(), { target: { value: "Attendance – October" } });
    submit();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    expect(bodyOf(fetcher, 2).requestKey).not.toBe(bodyOf(fetcher, 0).requestKey);
  });

  it("explains that only administrators can create cases", async () => {
    const fetcher = fetcherOf(reply(403, { error: "refused" }));
    render(<NewCaseForm companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} />);
    fireEvent.change(titleBox(), { target: { value: "Attendance" } });
    submit();
    expect(await screen.findByText("Only company administrators can create cases.")).toBeInTheDocument();
  });
});

describe("CaseWorkspace", () => {
  function renderWorkspace(initial = view(), fetcher = fetcherOf()) {
    render(
      <CaseWorkspace
        cases={[summary(), summary({ id: OTHER_CASE_ID, title: "[SYNTHETIC] Other case" })]}
        companyId={COMPANY_ID}
        fetcher={fetcher as unknown as typeof fetch}
        initialView={initial}
      />,
    );
    return fetcher;
  }
  const save = () => fireEvent.click(screen.getByRole("button", { name: /Save answers/ }));
  const narrative = () => screen.getByRole("textbox", { name: "What happened?" });

  it("renders the conversation, the question groups and the case context from the view", () => {
    renderWorkspace();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("[SYNTHETIC] Attendance concern");
    expect(screen.getByText(/guided workflow, no AI/)).toBeInTheDocument();
    const conversation = screen.getByRole("list", { name: "Conversation" });
    expect(within(conversation).getByText("This is a guided workflow, not an AI assistant.")).toBeInTheDocument();
    expect(within(conversation).getByText("Still to answer")).toBeInTheDocument();
    // The Company's jurisdiction isn't confirmed: a pause, shown as a hold.
    expect(within(conversation).getByText("Paused: jurisdiction not confirmed")).toBeInTheDocument();

    const details = screen.getByRole("complementary", { name: "Case details" });
    for (const label of ["Completed", "Needs information", "Blocked", "Coming later"]) {
      expect(within(details).getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(within(details).getByText("Expert review")).toBeInTheDocument();
    expect(within(details).getByText("No answers saved yet.")).toBeInTheDocument();
    expect(within(details).getByText("Waiting for your company's jurisdiction")).toBeInTheDocument();
    const history = within(details).getByRole("region", { name: "Case history" });
    expect(within(history).getByText("Case created")).toBeInTheDocument();
    expect(within(history).getByText(/· You/)).toBeInTheDocument();

    const sidebar = screen.getByRole("navigation", { name: "Cases" });
    expect(within(sidebar).getByRole("link", { current: "page" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    const groups = screen.getByRole("navigation", { name: "Question groups" });
    expect(within(groups).getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringContaining("1. Initial facts"),
      expect.stringContaining("2. Employment jurisdiction"),
      expect.stringContaining("3. Incident context"),
      expect.stringContaining("4. Safety screening"),
    ]);
    expect(within(groups).getByRole("button", { current: "step" })).toHaveTextContent("Initial facts");
    expect(screen.getByRole("heading", { name: "Initial facts", level: 2 })).toBeInTheDocument();
  });

  it("shows why a step can't be answered yet instead of its questions", () => {
    renderWorkspace();
    fireEvent.click(screen.getByRole("button", { name: /Safety screening/ }));
    expect(screen.getByText("Not available right now")).toBeInTheDocument();
    expect(screen.getByText("Available once the case's jurisdiction is confirmed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save answers/ })).toBeNull();
  });

  it("asks a follow-up only after the answer that needs it", () => {
    renderWorkspace(view({ company: "uae_federal" }));
    fireEvent.click(screen.getByRole("button", { name: /Incident context/ }));
    expect(screen.queryByRole("group", { name: /connected to work/ })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "No, outside work" }));
    expect(screen.getByRole("group", { name: /connected to work/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Yes, at work or while working" }));
    expect(screen.queryByRole("group", { name: /connected to work/ })).toBeNull();
  });

  it("offers the company's confirmed jurisdiction for this case", () => {
    renderWorkspace(view({ company: "uae_federal" }));
    fireEvent.click(screen.getByRole("button", { name: /Employment jurisdiction/ }));
    const group = screen.getByRole("group", { name: /confirmed employment jurisdiction/ });
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual([
      "Yes, UAE Federal (MOHRE)",
      "No, a different jurisdiction applies",
      "Not sure",
    ]);
  });

  it("marks the safety screening as provisional and saves the whole group", async () => {
    const confirmed = view({ company: "uae_federal", answers: { "jurisdiction.case_confirmation": "uae_federal" }, revision: 2 });
    const fetcher = renderWorkspace(confirmed, fetcherOf(reply(200, { view: confirmed })));
    fireEvent.click(screen.getByRole("button", { name: /Safety screening/ }));
    expect(screen.getByText(/haven't been legally reviewed yet/)).toBeInTheDocument();
    const groups = screen.getAllByRole("group");
    expect(groups).toHaveLength(9);
    for (const group of groups) fireEvent.click(within(group).getByRole("radio", { name: "No" }));
    fireEvent.click(within(groups[3]).getByRole("radio", { name: "Not sure" }));
    save();
    await screen.findByText("Your answers are saved to this case.");
    const [url] = fetcher.mock.calls[0] as [string];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/safety_screening/answers`);
    expect(bodyOf(fetcher).answers).toEqual({ ...ALL_CLEAR, "screening.sick_leave": "not_sure" });
  });

  it("shows a hold and cautions from the API without promising an expert", () => {
    renderWorkspace(view({ company: "uae_federal", hold: HIGH_RISK_HOLD, cautions: [POLICY_CAUTION] }));
    const conversation = screen.getByRole("list", { name: "Conversation" });
    expect(within(conversation).getByText("On hold: specialist review needed")).toBeInTheDocument();
    expect(within(conversation).getByText("Sick leave")).toBeInTheDocument();
    expect(within(conversation).getByText("Caution: Expected standard not explained")).toBeInTheDocument();
    expect(within(conversation).getAllByText("Provisional: not legal advice").length).toBe(2);
    const details = screen.getByRole("complementary", { name: "Case details" });
    expect(within(details).getByRole("heading", { name: "Hold" })).toBeInTheDocument();
    expect(within(details).getByRole("heading", { name: "Cautions" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/will contact|ticket|we'll be in touch/i);
    // A hold doesn't stop the employer correcting answers.
    expect(screen.getByRole("button", { name: /Save answers/ })).toBeInTheDocument();
  });

  it("is view only for a member", () => {
    renderWorkspace(view({ canEdit: false }));
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save answers/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
  });

  it("saves only the changed answers once and shows the saved turn", async () => {
    const after = view({ answers: { "incident.narrative": NARRATIVE, "incident.history": "new" }, revision: 1 });
    const fetcher = renderWorkspace(view(), fetcherOf(reply(200, { view: after })));
    fireEvent.change(narrative(), { target: { value: `${NARRATIVE}  ` } });
    fireEvent.click(screen.getByRole("radio", { name: "This is a new issue" }));
    const button = screen.getByRole("button", { name: /Save answers/ });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(await screen.findByText("Your answers are saved to this case.")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url] = fetcher.mock.calls[0] as [string];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/initial_facts/answers`);
    const body = bodyOf(fetcher);
    expect(body.expectedRevision).toBe(0);
    expect(body.submissionKey).toMatch(UUID);
    expect(body.answers).toEqual({ "incident.narrative": NARRATIVE, "incident.history": "new" });

    // The view is the API's answer: the employer's turn and the new progress.
    const conversation = screen.getByRole("list", { name: "Conversation" });
    expect(within(conversation).getByText("You")).toBeInTheDocument();
    expect(screen.getByText(/3 still to answer/)).toBeInTheDocument();
    const header = screen.getByRole("heading", { level: 1 }).closest("header")!;
    expect(header).toHaveTextContent(/2 of 9\s+intake questions answered/);
    // The next group with questions left is offered.
    fireEvent.click(screen.getByRole("button", { name: "Continue to Incident context" }));
    expect(screen.getByRole("heading", { name: "Incident context", level: 2 })).toBeInTheDocument();
  });

  it("asks to reload when the case changed since it was opened", async () => {
    const fetcher = renderWorkspace(view(), fetcherOf(reply(409, { error: "conflict" })));
    fireEvent.click(screen.getByRole("radio", { name: "This is a new issue" }));
    save();
    expect(await screen.findByText("This case has changed since you opened it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload the case" })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("marks the questions the API refused", async () => {
    renderWorkspace(view(), fetcherOf(reply(422, { error: "invalid", fields: ["incident.history"] })));
    fireEvent.click(screen.getByRole("radio", { name: "This is a new issue" }));
    save();
    expect(await screen.findByText("HeroOS couldn't accept this answer. Please check it.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Is this a new issue/ })).toHaveAttribute("aria-invalid", "true");
  });

  it("retries a lost save with the same submission key", async () => {
    const after = view({ answers: { "incident.history": "new" }, revision: 1 });
    const fetcher = renderWorkspace(view(), fetcherOf(new TypeError("network"), reply(200, { view: after })));
    fireEvent.click(screen.getByRole("radio", { name: "This is a new issue" }));
    save();
    expect(await screen.findByText("Your answers weren't saved")).toBeInTheDocument();
    save();
    await screen.findByText("Your answers are saved to this case.");
    expect(bodyOf(fetcher, 1).submissionKey).toBe(bodyOf(fetcher, 0).submissionKey);
  });

  it("clears an emptied answer and records an unknown date as not sure", async () => {
    const saved = view({ answers: { "incident.narrative": NARRATIVE }, revision: 4 });
    const fetcher = renderWorkspace(saved, fetcherOf(reply(200, { view: view({ revision: 5 }) })));
    fireEvent.change(narrative(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Not sure" }));
    save();
    await screen.findByText("Your answers are saved to this case.");
    expect(bodyOf(fetcher).answers).toEqual({ "incident.narrative": null, "incident.date": "not_sure" });
    expect(bodyOf(fetcher).expectedRevision).toBe(4);
  });

  it("says when there is nothing new to save", async () => {
    const fetcher = renderWorkspace();
    save();
    expect(await screen.findByText("Nothing new to save")).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
