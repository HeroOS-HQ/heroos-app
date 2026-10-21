import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { parseCaseSummary } from "@/lib/workflows/model";
import { COMPANY_ID } from "@/test/fixtures";
import {
  ALL_CLEAR,
  apiCaseSummary,
  CASE_ID,
  EARLIER_HOLD,
  HIGH_RISK_HOLD,
  NARRATIVE,
  OTHER_CASE_ID,
  POLICY_CAUTION,
  view,
  workspaceHeader,
} from "@/test/workflow-fixtures";

import { CaseWorkspace } from "./case-workspace";

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

describe("CaseWorkspace", () => {
  const OTHER = () => summary({ id: OTHER_CASE_ID, title: "[SYNTHETIC] Other case" });
  function renderWorkspace(initial = view(), fetcher = fetcherOf()) {
    render(
      <CaseWorkspace
        fetcher={fetcher as unknown as typeof fetch}
        header={workspaceHeader([summary(), OTHER()])}
        initialView={initial}
      />,
    );
    return fetcher;
  }
  const save = () => fireEvent.click(screen.getByRole("button", { name: /Save answers/ }));
  const narrative = () => screen.getByRole("textbox", { name: "What happened?" });
  const openStatus = () => {
    fireEvent.click(screen.getByRole("button", { name: /Case status$/ }));
    return within(screen.getByRole("dialog", { name: "[SYNTHETIC] Attendance concern" }));
  };

  it("is the case's conversation in the approved thread, then what HeroOS needs to know, without Hannah", () => {
    renderWorkspace();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("[SYNTHETIC] Attendance concern");
    const conversation = screen.getByRole("log", { name: "Conversation: [SYNTHETIC] Attendance concern" });
    expect(within(conversation).getByText("This is a guided workflow, not an AI assistant.")).toBeInTheDocument();
    expect(within(conversation).getByText("Still to answer")).toBeInTheDocument();
    // The Company's jurisdiction isn't confirmed: a pause, shown as a Block (its own words, the stop sign, never colour alone).
    const pause = within(conversation).getByRole("article", { name: "HeroOS, Stop" });
    expect(within(pause).getByText("Paused: jurisdiction not confirmed")).toBeInTheDocument();
    // HeroOS speaks; no mascot and no AI demo on the case page.
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Hannah|AI demo/);

    const answers = screen.getByRole("region", { name: "Your answers" });
    expect(within(answers).getByText("HeroOS needs to know")).toBeInTheDocument();
    const groups = within(answers).getByRole("navigation", { name: "Question groups" });
    expect(within(groups).getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringContaining("1. Initial facts"),
      expect.stringContaining("2. Employment jurisdiction"),
      expect.stringContaining("3. Incident context"),
      expect.stringContaining("4. Safety screening"),
    ]);
    expect(within(groups).getByRole("button", { current: "step" })).toHaveTextContent("Initial facts");
    expect(screen.getByRole("heading", { name: "Initial facts", level: 2 })).toBeInTheDocument();
  });

  it("names the case in the header, with a new question and the Cases drawer (search, the current case marked)", () => {
    const fetcher = renderWorkspace();
    const header = within(screen.getByRole("banner"));
    // The thread's turns are articles labelled by their headings, not page landmarks.
    expect(screen.getAllByRole("banner")).toHaveLength(1);
    expect(header.getByRole("button", { name: /^\[SYNTHETIC\] Attendance concern\. .*Case status$/ })).toHaveAttribute("aria-expanded", "false");
    expect(header.getByRole("link", { name: "New question" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}`);
    expect(header.queryByRole("link", { name: /Dashboard|HR Services|All cases/ })).toBeNull();

    fireEvent.click(header.getByRole("button", { name: "Cases" }));
    const drawer = within(screen.getByRole("dialog", { name: "Cases" }));
    const list = drawer.getByRole("navigation", { name: "Your cases" });
    expect(within(list).getAllByRole("link")).toHaveLength(2);
    expect(within(list).getByRole("link", { current: "page" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    fireEvent.change(drawer.getByRole("searchbox", { name: "Search your cases" }), { target: { value: "other" } });
    expect(within(list).getAllByRole("link").map((a) => a.textContent)).toEqual([expect.stringContaining("[SYNTHETIC] Other case")]);
    fireEvent.change(drawer.getByRole("searchbox", { name: "Search your cases" }), { target: { value: "no such case" } });
    expect(within(list).queryAllByRole("link")).toHaveLength(0);
    expect(drawer.getByText(/No cases match/)).toBeInTheDocument();
    expect(drawer.getByRole("link", { name: "New question" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}`);
    // Searching is local: nothing is requested.
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Cases" })).toBeNull();
  });

  it("opens the case status from the header: the hold (never folded), the next step, facts and history, the rest folded away", async () => {
    renderWorkspace();
    const pill = screen.getByRole("button", { name: /Case status$/ });
    const status = openStatus();
    expect(pill).toHaveAttribute("aria-expanded", "true");
    expect(status.getByText("Jurisdiction: Waiting for your company's jurisdiction")).toBeInTheDocument();
    const hold = status.getByRole("region", { name: /On hold/ });
    expect(hold.closest("details")).toBeNull();
    expect(within(hold).getByText("Paused: jurisdiction not confirmed")).toBeInTheDocument();
    expect(status.getByRole("region", { name: "Your next step" })).toHaveTextContent("Paused: jurisdiction not confirmed");
    expect(status.getByRole("region", { name: "Done so far" })).toBeInTheDocument();
    expect(status.getByRole("region", { name: "Still needed" })).toBeInTheDocument();
    expect(within(status.getByRole("region", { name: "What you've told HeroOS" })).getByText("Nothing saved yet.")).toBeInTheDocument();
    const history = status.getByRole("region", { name: "Case history" });
    expect(within(history).getByText("Case created")).toBeInTheDocument();

    // Everything else is one click (or Enter) away, closed at first.
    const full = document.querySelector("details#case-full-details") as HTMLDetailsElement;
    expect(full.open).toBe(false);
    for (const name of ["Case progress", "Known facts", "Missing information", "Not available yet"]) {
      expect(within(full).getByRole("region", { name })).toBeInTheDocument();
    }
    fireEvent.click(within(full).getByText("Full case details").closest("summary")!);
    expect(full.open).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(pill).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(pill).toHaveFocus());
  });

  it("shows no hold when the case has none, and the case's jurisdiction in how HeroOS tailored it", () => {
    renderWorkspace(view({ company: "uae_federal", answers: { "jurisdiction.case_confirmation": "uae_federal" } }));
    const status = openStatus();
    expect(status.queryByRole("region", { name: /On hold/ })).toBeNull();
    expect(status.getByText("Jurisdiction: UAE Federal (MOHRE)")).toBeInTheDocument();
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
    const groups = within(screen.getByRole("region", { name: "Your answers" })).getAllByRole("group");
    expect(groups).toHaveLength(9);
    for (const group of groups) fireEvent.click(within(group).getByRole("radio", { name: "No" }));
    fireEvent.click(within(groups[3]).getByRole("radio", { name: "Not sure" }));
    save();
    await screen.findByText("Your answers are saved to this case.");
    const [url] = fetcher.mock.calls[0] as [string];
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/safety_screening/answers`);
    expect(bodyOf(fetcher).answers).toEqual({ ...ALL_CLEAR, "screening.sick_leave": "not_sure" });
  });

  it("keeps an earlier escalation visible apart from the current screening", () => {
    const answers = { "jurisdiction.case_confirmation": "uae_federal", ...ALL_CLEAR };
    renderWorkspace(
      view({
        company: "uae_federal",
        answers,
        hold: EARLIER_HOLD,
        escalation: { since: "2026-10-16T09:00:00Z", reason: "high_risk_factors", current: false },
      }),
    );
    const hold = openStatus().getByRole("region", { name: /On hold/ });
    expect(within(hold).getByText("First held because: a screening answer needed specialist advice")).toBeInTheDocument();
    expect(within(hold).getByText("16 Oct 2026, 09:00 UTC")).toBeInTheDocument();
    expect(within(hold).getByText("Current screening")).toBeInTheDocument();
    expect(within(hold).getByText(/don't release the hold/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/cleared by|approved by|hold lifted/i);
  });

  it("asks for made-up examples only on the sensitive screening in a demo environment", () => {
    const confirmed = { company: "uae_federal" as const, answers: { "jurisdiction.case_confirmation": "uae_federal" } };
    renderWorkspace(view(confirmed));
    expect(screen.getByText(/Demo environment: use made-up examples only/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Safety screening/ }));
    expect(screen.getByText("Demo environment: made-up examples only")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Incident context/ }));
    expect(screen.queryByText("Demo environment: made-up examples only")).toBeNull();
  });

  it("explains that the screening isn't enabled where it is disabled", () => {
    renderWorkspace(view({ company: "uae_federal", answers: { "jurisdiction.case_confirmation": "uae_federal" }, screening: "disabled" }));
    expect(screen.queryByText(/Demo environment/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Safety screening/ }));
    expect(screen.getByText("The safety screening isn't enabled in this environment.")).toBeInTheDocument();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });

  it("shows a hold and cautions from the API without promising an expert", () => {
    renderWorkspace(view({ company: "uae_federal", hold: HIGH_RISK_HOLD, cautions: [POLICY_CAUTION] }));
    const conversation = screen.getByRole("log", { name: /^Conversation/ });
    // The hold for specialist review is Expert Review; the caution is a Warning (words and icons, not colour alone).
    const expert = within(conversation).getByRole("article", { name: "HeroOS, Expert Review" });
    expect(within(expert).getByText("On hold: specialist review needed")).toBeInTheDocument();
    expect(within(expert).getByText("Sick leave")).toBeInTheDocument();
    const warning = within(conversation).getByRole("article", { name: "HeroOS, Warning" });
    expect(within(warning).getByText("Expected standard not explained")).toBeInTheDocument();
    expect(within(conversation).getAllByText("Provisional: not legal advice").length).toBe(2);
    // No request button: HeroOS doesn't offer Expert Review in the app yet.
    expect(within(expert).queryByRole("button")).toBeNull();
    const status = openStatus();
    expect(status.getByRole("region", { name: /On hold/ })).toBeInTheDocument();
    expect(status.getByRole("heading", { name: "Cautions" })).toBeInTheDocument();
    expect(status.getByText("Caution: Expected standard not explained")).toBeInTheDocument();
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
    const conversation = screen.getByRole("log", { name: /^Conversation/ });
    expect(within(conversation).getByText("You")).toBeInTheDocument();
    expect(screen.getByText(/3 still to answer/)).toBeInTheDocument();
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
