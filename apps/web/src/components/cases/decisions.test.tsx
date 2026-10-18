import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";
import {
  apiDecisions,
  apiEntry,
  apiProgression,
  apiRecord,
  apiTimeline,
  CASE_ID,
  CORRECTION_ID,
  HIGH_RISK_HOLD,
  RECORD_ID,
  view,
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

const call = (fetcher: ReturnType<typeof fetcherOf>, index = 0) => {
  const [url, init] = fetcher.mock.calls[index] as [string, RequestInit | undefined];
  return { url, init, body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null };
};

type Overrides = Parameters<typeof view>[0];
const workspace = (overrides: Overrides, fetcher?: ReturnType<typeof fetcherOf>) =>
  render(
    <CaseWorkspace
      cases={[]}
      companyId={COMPANY_ID}
      fetcher={fetcher as unknown as typeof fetch}
      initialView={view({ company: "uae_federal", revision: 5, progression: apiProgression(), ...overrides })}
    />,
  );

const section = () => within(screen.getByRole("region", { name: "Decisions & history" }));
const records = () => within(screen.getByRole("region", { name: "Employer records" }));
const history = () => within(screen.getByRole("region", { name: "Case history" }));
// The entries themselves (the legend above them names the same kinds).
const entries = () => within(history().getByRole("list"));

function fillNewRecord() {
  fireEvent.click(section().getByRole("button", { name: "Add a record" }));
  fireEvent.click(screen.getByLabelText(/Internal review completed/));
  fireEvent.change(screen.getByRole("textbox", { name: "Short summary" }), {
    target: { value: "  [SYNTHETIC] Manager reviewed the shift logs " },
  });
  fireEvent.change(screen.getByLabelText("When did it happen?"), { target: { value: "2026-10-12" } });
  fireEvent.click(screen.getByLabelText(/Someone else in my company/));
  fireEvent.change(screen.getByRole("textbox", { name: "Their role or job title" }), {
    target: { value: "[SYNTHETIC] Operations lead" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "What happened, and why?" }), {
    target: { value: "[SYNTHETIC] Two weeks of logs compared.\nNothing else found." },
  });
  fireEvent.click(screen.getByLabelText(/Yes, my company holds supporting evidence/));
  fireEvent.change(screen.getByRole("combobox", { name: "Type" }), { target: { value: "internal_document" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "[SYNTHETIC] Handover log" } });
}

describe("Decisions & history", () => {
  it("says what a record is and isn't, lists only factual categories and the holds that still apply", () => {
    workspace({
      hold: HIGH_RISK_HOLD,
      decisions: apiDecisions(),
      timeline: apiTimeline(),
      progression: apiProgression({
        escalations: [{ transition: "complete:test_check_in", label: "Mark complete: Test stage 1", since: "2026-10-16T09:00:00Z" }],
      }),
    });
    expect(section().getByText("What a record is, and isn't")).toBeInTheDocument();
    expect(section().getByText(/isn't a warning, a penalty or any other disciplinary outcome/)).toBeInTheDocument();
    const holds = within(screen.getByRole("region", { name: "Holds and limits on this case" }));
    expect(holds.getByText("On hold: specialist review needed")).toBeInTheDocument();
    expect(holds.getByText(/A record doesn't release it/)).toBeInTheDocument();
    expect(holds.getByText("Specialist review needed: Mark complete: Test stage 1")).toBeInTheDocument();
    expect(holds.getByText(/Records don't start or complete stages, release holds/)).toBeInTheDocument();

    fireEvent.click(section().getByRole("button", { name: "Add a record" }));
    const categories = within(screen.getByRole("group", { name: "What are you recording?" }));
    expect(categories.getAllByRole("radio").map((radio) => (radio as HTMLInputElement).value)).toEqual([
      "internal_review_completed",
      "information_requested",
      "meeting_recorded",
      "employer_observation",
      "internal_pause_or_follow_up",
      "other_note",
    ]);
    expect(screen.queryByText(/formal warning issued/i)).toBeNull();
  });

  it("never offers a category this version doesn't know, whatever the payload says", () => {
    const options = apiDecisions().options as Record<string, unknown>;
    const forged = {
      ...options,
      categories: [...(options.categories as unknown[]), { key: "formal_warning_issued", label: "Formal warning issued", description: "x" }],
    };
    workspace({ decisions: apiDecisions([], { options: forged }), timeline: apiTimeline() });
    fireEvent.click(section().getByRole("button", { name: "Add a record" }));
    expect(screen.queryByLabelText(/Formal warning issued/)).toBeNull();
  });

  it("checks the form before sending anything", () => {
    const fetcher = fetcherOf();
    workspace({ decisions: apiDecisions(), timeline: apiTimeline() }, fetcher);
    fireEvent.click(section().getByRole("button", { name: "Add a record" }));
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    const alert = screen.getByRole("alert");
    for (const text of [
      "Choose what you're recording.",
      "Write a short summary.",
      "Enter the date it happened.",
      "Say who is responsible.",
      "Explain what happened or what was decided.",
      "Say whether supporting evidence exists.",
    ]) {
      expect(within(alert).getByText(text)).toBeInTheDocument();
    }
    expect(fetcher).not.toHaveBeenCalled();

    // Editing a field removes its error at once; the others stay until fixed.
    fireEvent.change(screen.getByRole("textbox", { name: "Short summary" }), { target: { value: "[SYNTHETIC] Summary" } });
    expect(within(screen.getByRole("alert")).queryByText("Write a short summary.")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Short summary" })).not.toHaveAttribute("aria-invalid");
    expect(within(screen.getByRole("alert")).getByText("Choose what you're recording.")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Yes, my company holds supporting evidence/));
    expect(within(screen.getByRole("alert")).queryByText("Say whether supporting evidence exists.")).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "https://files.example.invalid/x" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Type" }), { target: { value: "policy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    expect(within(screen.getByRole("alert")).getByText(/instead of a link/)).toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("saves a record once, shows it at once and says the workflow didn't change", async () => {
    const saved = apiRecord({
      id: RECORD_ID,
      chain_id: RECORD_ID,
      category: "internal_review_completed",
      category_label: "Internal review completed",
      summary: "[SYNTHETIC] Manager reviewed the shift logs",
    });
    const after = view({
      company: "uae_federal",
      revision: 6,
      progression: apiProgression(),
      decisions: apiDecisions([saved], { saved: RECORD_ID }),
      timeline: apiTimeline([
        apiEntry(`decision:${RECORD_ID}`, {
          category: "decisions",
          kind: "decision_recorded",
          nature: "employer_record",
          title: "Employer record: Internal review completed",
          detail: "“[SYNTHETIC] Manager reviewed the shift logs”",
          status: "current",
          source: { type: "decision_record", id: RECORD_ID },
          link: { relation: null, supersedes: null, superseded_by: null },
        }),
        apiEntry("created"),
      ]),
    });
    const fetcher = fetcherOf(reply(200, { view: after }));
    workspace({ decisions: apiDecisions(), timeline: apiTimeline() }, fetcher);
    fillNewRecord();
    const save = screen.getByRole("button", { name: "Save record" });
    fireEvent.click(save);
    fireEvent.click(save);

    await screen.findByText("Record saved");
    expect(fetcher).toHaveBeenCalledTimes(1);
    const { url, init, body } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/decisions`);
    expect(init?.method).toBe("POST");
    expect(body).toEqual({
      expectedRevision: 5,
      requestKey: expect.stringMatching(UUID),
      category: "internal_review_completed",
      summary: "[SYNTHETIC] Manager reviewed the shift logs",
      explanation: "[SYNTHETIC] Two weeks of logs compared.\nNothing else found.",
      occurredOn: "2026-10-12",
      decisionMaker: "other",
      decisionMakerRole: "[SYNTHETIC] Operations lead",
      evidenceStatus: "held",
      evidence: [{ kind: "internal_document", description: "[SYNTHETIC] Handover log", reference: null }],
    });
    // Nothing in the request names an actor or an approval: the API takes the session's.
    expect(Object.keys(body!)).not.toContain("recordedBy");
    expect(screen.getByText(/The workflow hasn't changed: holds, stages and next steps are as they were/)).toBeInTheDocument();
    expect(records().getByText("[SYNTHETIC] Manager reviewed the shift logs")).toBeInTheDocument();
    expect(entries().getByText("Employer record: Internal review completed")).toBeInTheDocument();
    expect(entries().getByText("Employer record")).toBeInTheDocument();
  });

  it("retries a lost request with the same key and explains a conflict", async () => {
    const fetcher = fetcherOf(new TypeError("network"), reply(409, { error: "conflict" }));
    workspace({ decisions: apiDecisions(), timeline: apiTimeline() }, fetcher);
    fillNewRecord();
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    await screen.findByText("Nothing was saved");
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    await screen.findByText("This case has changed since you opened it");
    expect(call(fetcher, 1).body!.requestKey).toBe(call(fetcher, 0).body!.requestKey);
  });

  it("names the fields the API refused", async () => {
    const fetcher = fetcherOf(reply(422, { error: "invalid", fields: ["evidence", "occurred_on"] }));
    workspace({ decisions: apiDecisions(), timeline: apiTimeline() }, fetcher);
    fillNewRecord();
    fireEvent.click(screen.getByRole("button", { name: "Save record" }));
    await screen.findByText("Some details need attention");
    expect(screen.getByLabelText("When did it happen?")).toHaveAttribute("aria-invalid", "true");
  });

  it("corrects the current version as a new version and keeps the earlier one", async () => {
    const original = apiRecord();
    const corrected = apiRecord({
      id: CORRECTION_ID,
      version: 2,
      relation: "correction",
      supersedes: RECORD_ID,
      occurred_on: "2026-10-13",
      change_reason: "[SYNTHETIC] The meeting date was wrong.",
      recorded_at: "2026-10-16T11:00:00Z",
    });
    const after = view({
      company: "uae_federal",
      revision: 6,
      progression: apiProgression(),
      decisions: apiDecisions([corrected, { ...original, current: false, superseded_by: CORRECTION_ID }], { saved: CORRECTION_ID }),
      timeline: apiTimeline(),
    });
    const fetcher = fetcherOf(reply(200, { view: after }));
    workspace({ decisions: apiDecisions([original]), timeline: apiTimeline() }, fetcher);

    expect(records().getByText("Current")).toBeInTheDocument();
    expect(records().getByText("[SYNTHETIC] Shift supervisor (as stated by your company)")).toBeInTheDocument();
    expect(records().getByText(/Your company's account. HeroOS hasn't verified it./)).toBeInTheDocument();
    fireEvent.click(records().getByRole("button", { name: "Correct" }));
    // Pre-filled from the version it replaces.
    expect(screen.getByRole("textbox", { name: "Short summary" })).toHaveValue("[SYNTHETIC] Check-in meeting held");
    fireEvent.change(screen.getByLabelText("When did it happen?"), { target: { value: "2026-10-13" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(within(screen.getByRole("alert")).getByText("Say why you're making this change.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Why are you correcting it?" }), {
      target: { value: "[SYNTHETIC] The meeting date was wrong." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    await screen.findByText("Correction saved");
    const { url, body } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/decisions/${RECORD_ID}/corrections`);
    expect(body).toMatchObject({ relation: "correction", changeReason: "[SYNTHETIC] The meeting date was wrong.", occurredOn: "2026-10-13" });
    expect(records().getByText("Corrected · version 2")).toBeInTheDocument();
    const earlier = records().getByText("Earlier versions (1), kept in the history").closest("details")!;
    expect(within(earlier).getByText("Replaced")).toBeInTheDocument();
    expect(within(earlier).getByText("First record · version 1 · Meeting or discussion recorded")).toBeInTheDocument();
  });

  it("labels every history entry by what it is and loads older entries", async () => {
    const older = {
      entries: [
        {
          id: "created",
          at: "2026-10-15T09:00:00Z",
          category: "case",
          kind: "case_created",
          nature: "workflow_change",
          title: "Case created",
          detail: null,
          byViewer: true,
          status: null,
          link: null,
        },
      ],
      nextBefore: null,
      total: 3,
    };
    const fetcher = fetcherOf(reply(200, { page: older }));
    workspace(
      {
        decisions: apiDecisions(),
        timeline: apiTimeline(
          [
            apiEntry("progress:aaaa", {
              category: "progression",
              kind: "transition_rejected",
              nature: "refused_request",
              title: "Not allowed: Start: Test stage 2",
              detail: "Not the next stage. The case didn't move on.",
              status: "refused",
            }),
            apiEntry("evaluation:x:hold", {
              category: "intake",
              kind: "hold_placed",
              nature: "system_check",
              title: "Case held for specialist review",
              status: "on_hold",
              by_viewer: null,
            }),
          ],
          { next_before: "evaluation:x:hold", total: 3 },
        ),
      },
      fetcher,
    );
    expect(entries().getByText("Not allowed: nothing changed")).toBeInTheDocument();
    expect(entries().getByText("Refused")).toBeInTheDocument();
    expect(entries().getByText("HeroOS check")).toBeInTheDocument();
    expect(entries().getByText("On hold")).toBeInTheDocument();
    expect(history().getByText("Showing 2 of 3 entries.")).toBeInTheDocument();

    fireEvent.click(history().getByRole("button", { name: "Show older entries" }));
    await waitFor(() => expect(history().getByText("Case created")).toBeInTheDocument());
    const { url, init } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/history?before=evaluation%3Ax%3Ahold`);
    expect(init?.method ?? "GET").toBe("GET");
    expect(history().getByText("Showing 3 of 3 entries.")).toBeInTheDocument();
    expect(history().queryByRole("button", { name: "Show older entries" })).toBeNull();
    expect(entries().getByText("Workflow step")).toBeInTheDocument();
  });

  it("is view only for anyone who can't edit", () => {
    workspace({ canEdit: false, decisions: apiDecisions([apiRecord()]), timeline: apiTimeline() });
    expect(section().queryByRole("button", { name: "Add a record" })).toBeNull();
    expect(records().queryByRole("button", { name: "Correct" })).toBeNull();
    expect(section().getByText("Only company administrators can add or correct records.")).toBeInTheDocument();
  });

  it("falls back to the earlier histories against an API without M2-04", () => {
    workspace({});
    expect(section().getByText("Decision records aren't available yet")).toBeInTheDocument();
    const details = within(screen.getByRole("complementary", { name: "Case details" }));
    expect(details.getByRole("region", { name: "Case history" })).toBeInTheDocument();
  });

  it("moves the case history out of the side panel when the unified history exists", () => {
    workspace({ decisions: apiDecisions(), timeline: apiTimeline() });
    const details = within(screen.getByRole("complementary", { name: "Case details" }));
    expect(details.queryByRole("region", { name: "Case history" })).toBeNull();
    expect(details.getByRole("link", { name: "See the case history" })).toHaveAttribute("href", "#case-history");
    expect(history().getByText("Case created")).toBeInTheDocument();
  });
});
