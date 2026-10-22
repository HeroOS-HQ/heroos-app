import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANY_ID } from "@/test/fixtures";
import {
  apiProgression,
  pathwayOptions,
  CASE_ID,
  CHOSEN,
  inStageProgression,
  message,
  transition,
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

const call = (fetcher: ReturnType<typeof fetcherOf>, index = 0) => {
  const [url, init] = fetcher.mock.calls[index] as [string, RequestInit];
  return { url, body: JSON.parse(String(init.body)) as Record<string, unknown> };
};

const workspace = (progression: Record<string, unknown> | undefined, fetcher?: ReturnType<typeof fetcherOf>, canEdit = true) =>
  render(
    <CaseWorkspace
      header={workspaceHeader()}
      fetcher={fetcher as unknown as typeof fetch}
      initialView={view({ company: "uae_federal", revision: 4, canEdit, progression })}
    />,
  );

const nextSteps = () => within(screen.getByRole("region", { name: "Next steps" }));

describe("Next steps (workflow progression)", () => {
  it("fails closed against an API that doesn't send progression", () => {
    workspace(undefined);
    expect(nextSteps().getByText("Next steps aren't available")).toBeInTheDocument();
    expect(nextSteps().queryByRole("button")).toBeNull();
  });

  it("announces synthetic test rules and records the employer's own pathway choice", async () => {
    const after = view({
      company: "uae_federal",
      revision: 5,
      progression: apiProgression({
        status: { code: "ready", label: "Ready for the next stage" },
        pathway: CHOSEN,
        pathway_options: pathwayOptions("less_serious"),
        attempt: {
          request_key: "a1b2c3d4-0000-4000-8000-0000000000ee",
          transition: "pathway:less_serious",
          label: "Record pathway: Less serious",
          outcome: "applied",
          decision: "allow",
          title: "Recorded",
          body: "Record pathway: Less serious. This is recorded in the case history.",
        },
      }),
    });
    const fetcher = fetcherOf(reply(200, { view: after }));
    workspace(apiProgression(), fetcher);

    expect(nextSteps().getByText("Synthetic test rules")).toBeInTheDocument();
    expect(nextSteps().getByText(/it's your decision\. HeroOS can explain the choices in Ask HeroOS, but it doesn't classify the incident, choose a pathway for you or validate your choice/)).toBeInTheDocument();
    const record = nextSteps().getByRole("button", { name: "Record my decision" });
    expect(record).toBeDisabled();
    fireEvent.click(nextSteps().getByRole("radio", { name: /Less serious/ }));
    expect(record).toBeEnabled();
    fireEvent.click(record);

    await waitFor(() => expect(nextSteps().getByText("Recorded")).toBeInTheDocument());
    const { url, body } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/pathway`);
    expect(body).toMatchObject({ expectedRevision: 4, pathway: "less_serious", acknowledgedWarnings: [] });
    expect(body.requestKey).toMatch(UUID);
    expect(nextSteps().getByText("(your decision)")).toBeInTheDocument();
    expect(nextSteps().getByRole("button", { name: "Change pathway" })).toBeInTheDocument();
  });

  it("asks for an acknowledgment of exactly the cautions the API names", async () => {
    const warned = apiProgression({
      pathway_options: pathwayOptions(null, {
        less_serious: {
          decision: "warn",
          warnings: [message("test_select_history_caution", "warn", "Test caution: the issue was raised before")],
          acknowledge: ["test_select_history_caution"],
        },
      }),
    });
    const fetcher = fetcherOf(reply(200, { view: view({ company: "uae_federal", revision: 5, progression: apiProgression() }) }));
    workspace(warned, fetcher);
    fireEvent.click(nextSteps().getByRole("radio", { name: /Less serious/ }));
    expect(nextSteps().getByText("Test caution: the issue was raised before")).toBeInTheDocument();
    const record = nextSteps().getByRole("button", { name: "Record my decision" });
    expect(record).toBeDisabled();
    fireEvent.click(nextSteps().getByRole("checkbox", { name: /I've read this caution/ }));
    fireEvent.click(record);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(call(fetcher).body.acknowledgedWarnings).toEqual(["test_select_history_caution"]);
  });

  it("offers no way around a refused choice", () => {
    workspace(
      apiProgression({
        pathway_options: pathwayOptions(null, {
          serious: {
            decision: "block",
            allowed: false,
            reasons: [message("pathway_not_covered", "block", "Not available for this pathway yet", "engine")],
          },
        }),
      }),
    );
    const serious = nextSteps().getByRole("radio", { name: /Serious misconduct/ });
    expect(serious).toBeDisabled();
    expect(nextSteps().getByText("Not available for this pathway yet")).toBeInTheDocument();
  });

  it("shows a hold on the whole case with no actions at all", () => {
    workspace(
      inStageProgression({
        status: { code: "held", label: "On hold: specialist review needed" },
        gate: { code: "case_held", title: "On hold: specialist review needed", body: "This case is held for specialist review." },
        actions: [
          transition("complete:test_check_in", "Mark complete: Test stage 1", {
            decision: "escalate",
            allowed: false,
            reasons: [message("case_held", "escalate", "On hold: specialist review needed", "engine")],
          }),
        ],
        checklist: null,
      }),
    );
    expect(nextSteps().getByText("This case is held for specialist review.")).toBeInTheDocument();
    expect(nextSteps().queryByRole("button", { name: /Mark this stage complete|Start this stage|Record my decision/ })).toBeNull();
    expect(nextSteps().queryByRole("button", { name: "Change pathway" })).toBeNull();
    expect(nextSteps().getByText("Can't continue without specialist review")).toBeInTheDocument();
  });

  it("shows the stage in progress, what's still needed and the checklist through the answers route", async () => {
    const fetcher = fetcherOf(
      reply(200, { view: view({ company: "uae_federal", revision: 5, progression: inStageProgression() }) }),
    );
    workspace(inStageProgression(), fetcher);
    // The case status names the stage in progress.
    fireEvent.click(screen.getByRole("button", { name: /Case status$/ }));
    expect(within(screen.getByRole("dialog")).getByText(/Test stage 1: Check-in conversation/, { selector: "p" })).toHaveTextContent(
      "Now: Test stage 1: Check-in conversation",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(nextSteps().getByText("In progress")).toBeInTheDocument();
    expect(nextSteps().getByText("Checklist not complete")).toBeInTheDocument();
    expect(nextSteps().getByText("Employee's view heard (test)", { selector: "li" })).toBeInTheDocument();
    // Refused: explained, never a button.
    expect(nextSteps().queryByRole("button", { name: "Mark this stage complete" })).toBeNull();

    const checklist = within(screen.getByRole("region", { name: "Stage checklist" }));
    fireEvent.click(checklist.getAllByRole("radio", { name: "Yes" })[0]);
    fireEvent.click(checklist.getByRole("button", { name: "Save checklist" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const { url, body } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/test_check_in/answers`);
    expect(body.answers).toEqual({ "progress.test_check_in.conversation_held": "yes" });
  });

  it("requests an allowed transition and reports a refusal the API recorded", async () => {
    const allowed = inStageProgression({
      actions: [transition("complete:test_check_in", "Mark complete: Test stage 1: Check-in conversation")],
    });
    const refused = inStageProgression({
      attempt: {
        request_key: "a1b2c3d4-0000-4000-8000-0000000000ef",
        transition: "complete:test_check_in",
        label: "Mark complete: Test stage 1",
        outcome: "rejected",
        decision: "block",
        title: "Not allowed",
        body: "Mark complete: Test stage 1 isn't allowed right now, so the case didn't move on.",
      },
    });
    const fetcher = fetcherOf(reply(200, { view: view({ company: "uae_federal", revision: 4, progression: refused }) }));
    workspace(allowed, fetcher);
    fireEvent.click(nextSteps().getByRole("button", { name: "Mark this stage complete" }));
    await waitFor(() => expect(nextSteps().getByText("Not allowed")).toBeInTheDocument());
    const { url, body } = call(fetcher);
    expect(url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/transitions`);
    expect(body).toMatchObject({ expectedRevision: 4, transition: "complete:test_check_in", acknowledgedWarnings: [] });
  });

  it("asks to reload on a conflict and reuses the key only to retry a lost request", async () => {
    const allowed = inStageProgression({ actions: [transition("complete:test_check_in", "Mark complete")] });
    const fetcher = fetcherOf(new Error("network down"), reply(409, { error: "conflict" }));
    workspace(allowed, fetcher);
    const button = nextSteps().getByRole("button", { name: "Mark this stage complete" });
    fireEvent.click(button);
    await waitFor(() => expect(nextSteps().getByText("Nothing was recorded")).toBeInTheDocument());
    fireEvent.click(nextSteps().getByRole("button", { name: "Mark this stage complete" }));
    await waitFor(() => expect(nextSteps().getByText("This case has changed since you opened it")).toBeInTheDocument());
    expect(call(fetcher, 1).body.requestKey).toBe(call(fetcher, 0).body.requestKey);
    expect(nextSteps().getByRole("button", { name: "Reload the case" })).toBeInTheDocument();
  });

  it("lists unresolved specialist reviews and the progression history", () => {
    workspace(
      inStageProgression({
        escalations: [
          { transition: "complete:test_final_review", label: "Mark complete: Test stage 3", since: "2026-10-16T11:00:00Z" },
        ],
        history: [
          {
            id: "progress:1",
            kind: "pathway_selected",
            at: "2026-10-16T10:00:00Z",
            by_viewer: true,
            title: "Pathway recorded: Less serious (your decision)",
            detail: "Recorded as the employer's judgement. HeroOS didn't classify the incident.",
          },
        ],
      }),
    );
    expect(nextSteps().getByText("Mark complete: Test stage 3")).toBeInTheDocument();
    expect(nextSteps().getByText(/hasn't contacted anyone/)).toBeInTheDocument();
    // The step's hold is visible at the top of Next steps, not only further down...
    expect(nextSteps().getAllByText("Specialist review needed")[0]).toBeInTheDocument();
    // ...and it is that step's, never the whole Case's status (M2-NEW-08): the header keeps the Case's own.
    const pill = screen.getByRole("button", { name: /Case status$/ });
    expect(pill).not.toHaveTextContent("Specialist review needed");
    fireEvent.click(pill);
    expect(screen.getByText(/^Specialist review needed before: /)).toBeInTheDocument();
    const details = within(document.querySelector("details#case-full-details") as HTMLElement);
    expect(details.getByRole("heading", { name: "Progression history" })).toBeInTheDocument();
    expect(details.getByText("Pathway recorded: Less serious (your decision)")).toBeInTheDocument();
  });

  it("gives members a view without any action", () => {
    workspace(inStageProgression({ actions: [transition("complete:test_check_in", "Mark complete")] }), undefined, false);
    expect(nextSteps().queryByRole("button")).toBeNull();
    expect(screen.queryByRole("region", { name: "Stage checklist" })).toBeNull();
    expect(nextSteps().getByText("Only company administrators can move the case on.")).toBeInTheDocument();
  });
});
