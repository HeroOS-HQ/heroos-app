import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { isGreeting } from "@/lib/ask/model";
import type { WorkflowView } from "@/lib/workflows/model";
import { parseConversationDetail } from "@/lib/ask/conversation";
import { COMPANY_ID } from "@/test/fixtures";
import {
  ALL_CLEAR,
  apiProgression,
  CASE_ID,
  CHOSEN,
  HIGH_RISK_HOLD,
  inStageProgression,
  message,
  pathwayOptions,
  transition,
  view,
} from "@/test/workflow-fixtures";

import { AskWorkspace } from "./ask-workspace";
import { CaseSteps, nextCaseStep } from "./case-steps";

/**
 * M2-NEW-08: the Case is chat-first. Its own formal steps appear inline in Ask
 * HeroOS, one at a time, from the Case's view; every button calls the Case's
 * existing routes, and only the founder's click takes one. A greeting is never
 * a case.
 */

const COMPLETE: Record<string, string> = {
  "incident.narrative": "[SYNTHETIC] Three days absent.",
  "incident.date": "2026-10-10",
  "incident.history": "new",
  "incident.discussed_with_employee": "no",
  "incident.evidence_available": "yes",
  "jurisdiction.case_confirmation": "uae_federal",
  "context.location": "at_work",
  "history.same_incident_sanction": "no",
  "context.policy_awareness": "yes",
  "evidence.witnesses": "no",
  ...ALL_CLEAR,
};
const json = (code: number, body: unknown) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
// The Case's view as the BFF sends it (parsed by the BFF, then by the browser again).
const recorded = (progression: Record<string, unknown>, revision = 7, extra: Record<string, string> = {}): WorkflowView => {
  const parsed = view({ company: "uae_federal", answers: COMPLETE, revision, progression, hold: null });
  return { ...parsed, answers: { ...parsed.answers, ...extra } };
};

function setup(first: WorkflowView, ...after: Response[]) {
  const queue = [...after];
  const fetcher = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async (input) => {
    if (input.endsWith("/workflow")) return json(200, { view: first });
    return queue.shift() ?? json(503, { error: "unavailable" });
  });
  const changed = vi.fn();
  render(<CaseSteps caseId={CASE_ID} companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} onChanged={changed} revision={3} />);
  return { fetcher, changed };
}

const sent = (fetcher: ReturnType<typeof setup>["fetcher"]) =>
  fetcher.mock.calls
    .filter(([url]) => !url.endsWith("/workflow"))
    .map(([url, init]) => ({ url, method: init?.method, body: JSON.parse(String(init?.body)) as Record<string, unknown> }));

describe("the next Case step (pure)", () => {
  it("is nothing for a member, and a hold before anything else", () => {
    expect(nextCaseStep(view({ canEdit: false }))).toBeNull();
    const held = nextCaseStep(view({ company: "uae_federal", hold: HIGH_RISK_HOLD }));
    expect(held).toMatchObject({ kind: "hold", title: "On hold: specialist review needed" });
  });

  it("asks only what the conversation never collects, one question at a time, and leaves ordinary details to the chat", () => {
    // The jurisdiction for this employee: the employer's own answer, inline.
    const jurisdiction = nextCaseStep(view({ company: "uae_federal" }));
    expect(jurisdiction).toMatchObject({ kind: "question", stepKey: "jurisdiction" });
    // The safety screening (sensitive): asked inline, never by the AI, its questions in one card.
    const answered = { ...COMPLETE };
    for (const key of Object.keys(ALL_CLEAR)) delete answered[key];
    const screening = nextCaseStep(view({ company: "uae_federal", answers: answered, hold: null }));
    expect(screening).toMatchObject({ kind: "screening", stepKey: "safety_screening" });
    expect(screening?.kind === "screening" && screening.questions.map((q) => q.key).sort()).toEqual(Object.keys(ALL_CLEAR).sort());
    // Only ordinary details left: the conversation collects them; no card sends the founder to the form.
    const ordinary = { ...COMPLETE };
    delete ordinary["incident.date"];
    expect(nextCaseStep(view({ company: "uae_federal", answers: ordinary, hold: null }))).toBeNull();
  });

  it("follows the formal workflow: pathway, checklist, then the transition the API allows", () => {
    expect(nextCaseStep(view({ company: "uae_federal", answers: COMPLETE, hold: null, progression: apiProgression() }))).toMatchObject({
      kind: "pathway",
    });
    const checklist = nextCaseStep(view({ company: "uae_federal", answers: COMPLETE, hold: null, progression: inStageProgression() }));
    expect(checklist).toMatchObject({ kind: "checklist", stepKey: "test_check_in", question: { key: "progress.test_check_in.conversation_held" } });
    const ready = recorded(
      inStageProgression({ actions: [transition("complete:test_check_in", "Mark complete: Test stage 1: Check-in conversation")] }),
      7,
      { "progress.test_check_in.conversation_held": "yes", "progress.test_check_in.employee_heard": "yes" },
    );
    expect(nextCaseStep(ready)).toMatchObject({ kind: "transition", transition: { key: "complete:test_check_in" } });
    const refused = view({
      company: "uae_federal",
      answers: COMPLETE,
      hold: null,
      progression: apiProgression({
        pathway: CHOSEN,
        pathway_options: pathwayOptions("less_serious"),
        actions: [
          transition("start:test_check_in", "Start: Test stage 1: Check-in conversation", {
            decision: "escalate",
            allowed: false,
            reasons: [message("earlier_escalation", "escalate", "Specialist review needed", "engine")],
          }),
        ],
      }),
    });
    expect(nextCaseStep(refused)).toMatchObject({ kind: "refused" });
  });
});

describe("CaseSteps in Ask HeroOS", () => {
  it("offers the pathway as the employer's own decision and records it through the Case's route", async () => {
    const after = recorded(
      apiProgression({
        status: { code: "ready", label: "Ready for the next stage" },
        pathway: { ...CHOSEN, key: "serious", label: "Serious misconduct" },
        pathway_options: pathwayOptions("serious"),
        actions: [transition("start:test_notice", "Start: Test stage A: Written notice")],
        attempt: {
          request_key: "a1b2c3d4-0000-4000-8000-0000000000ee",
          transition: "pathway:serious",
          label: "Record pathway: Serious misconduct",
          outcome: "applied",
          decision: "allow",
          title: "Recorded",
          body: "Record pathway: Serious misconduct. This is recorded in the case history.",
        },
      }),
      8,
    );
    const { fetcher, changed } = setup(recorded(apiProgression()), json(200, { view: after }));
    const step = await screen.findByRole("region", { name: "Your case's next step" });
    expect(step).toHaveTextContent("Your company now needs to choose the pathway for this case");
    expect(step).toHaveTextContent("HeroOS doesn't classify the conduct");
    const choices = within(step).getByRole("group", { name: "Your pathway decision" });
    expect(within(choices).getAllByRole("button").map((b) => b.firstChild?.textContent)).toEqual([
      "Less serious",
      "Serious misconduct",
      "Unable to determine: needs review",
    ]);
    fireEvent.click(within(choices).getByRole("button", { name: /^Serious misconduct/ }));

    expect(await screen.findByText(/^Recorded: Serious misconduct is your company's decision for this case\./)).toBeInTheDocument();
    const [request] = sent(fetcher);
    expect(request.url).toBe(`/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/pathway`);
    expect(request.body).toMatchObject({ expectedRevision: 7, pathway: "serious", acknowledgedWarnings: [] });
    expect(changed).toHaveBeenCalledTimes(1);
    // The next step follows from the API's answer: start the first stage, by the founder's click.
    expect(screen.getByRole("button", { name: "Start Test stage A: Written notice" })).toBeInTheDocument();
  });

  it("asks a stage's checklist one question at a time, then offers to complete it", async () => {
    const after = recorded(inStageProgression(), 8, { "progress.test_check_in.conversation_held": "yes" });
    const { fetcher } = setup(recorded(inStageProgression()), json(200, { view: after }));
    const step = await screen.findByRole("region", { name: "Your case's next step" });
    expect(step).toHaveTextContent("Test stage 1: Check-in conversation needs your answer before it can be marked complete");
    expect(step).toHaveTextContent("Has the test check-in conversation taken place?");
    fireEvent.click(within(step).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(screen.getByText("Did the employee give their view?")).toBeInTheDocument());
    const [request] = sent(fetcher);
    expect(request).toMatchObject({
      url: `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/test_check_in/answers`,
      method: "PUT",
      body: { expectedRevision: 7, answers: { "progress.test_check_in.conversation_held": "yes" } },
    });
  });

  it("shows a caution with I understand before the step, and sends exactly the cautions acknowledged", async () => {
    const caution = message("test_note_evidence_caution", "warn", "Evidence caution");
    const progression = inStageProgression({
      checklist: null,
      actions: [
        transition("complete:test_check_in", "Mark complete: Test stage 1: Check-in conversation", {
          decision: "warn",
          warnings: [caution],
          acknowledge: ["test_note_evidence_caution"],
        }),
      ],
    });
    const { fetcher } = setup(recorded(progression), json(200, { view: recorded(progression, 8) }));
    const step = await screen.findByRole("region", { name: "Your case's next step" });
    expect(within(step).getByRole("article", { name: "HeroOS, Warning" })).toHaveTextContent("Evidence caution");
    expect(within(step).queryByRole("button", { name: /Mark complete/ })).toBeNull();
    fireEvent.click(within(step).getByRole("button", { name: "I understand" }));
    fireEvent.click(within(step).getByRole("button", { name: /^Mark complete: Test stage 1/ }));
    await waitFor(() => expect(sent(fetcher)).toHaveLength(1));
    expect(sent(fetcher)[0]).toMatchObject({
      url: `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/progression/transitions`,
      body: { transition: "complete:test_check_in", acknowledgedWarnings: ["test_note_evidence_caution"] },
    });
  });

  it("asks the employee's jurisdiction inline through the answers route, and nothing for a member", async () => {
    const first = view({ company: "uae_federal" });
    const { fetcher } = setup(first, json(200, { view: view({ company: "uae_federal", answers: { "jurisdiction.case_confirmation": "uae_federal" }, revision: 1 }) }));
    const step = await screen.findByRole("region", { name: "Your case's next step" });
    expect(step).toHaveTextContent("One quick check for your case record:");
    const options = within(step).getByRole("group", { name: "Employment jurisdiction for this case" });
    fireEvent.click(within(options).getAllByRole("button")[0]);
    await waitFor(() => expect(sent(fetcher)).toHaveLength(1));
    expect(sent(fetcher)[0]).toMatchObject({
      url: `/bff/companies/${COMPANY_ID}/cases/${CASE_ID}/steps/jurisdiction/answers`,
      method: "PUT",
      body: { answers: { "jurisdiction.case_confirmation": "uae_federal" } },
    });
  });

  it("says a refusal plainly, from the API's own words, and points to the case details", async () => {
    setup(
      recorded(
        apiProgression({
          pathway: CHOSEN,
          pathway_options: pathwayOptions("less_serious"),
          actions: [
            transition("start:test_check_in", "Start: Test stage 1: Check-in conversation", {
              decision: "escalate",
              allowed: false,
              reasons: [message("earlier_escalation", "escalate", "Specialist review needed", "engine")],
            }),
          ],
        }),
      ),
    );
    const step = await screen.findByRole("region", { name: "Your case's next step" });
    const held = within(step).getByRole("article", { name: "HeroOS, Expert Review" });
    expect(held).toHaveTextContent("Specialist review needed: Start: Test stage 1: Check-in conversation");
    expect(within(held).getByRole("link", { name: "Review case details" })).toHaveAttribute("href", `/workspaces/${COMPANY_ID}/cases/${CASE_ID}`);
    expect(within(step).queryByRole("button")).toBeNull();
    expect(step.textContent).not.toMatch(/submitted|ticket|will contact/i);
  });
});

describe("a greeting is never a case", () => {
  it.each(["Hi Hannah", "hello!", "Good morning HeroOS", "hey there"])("%s is a greeting", (text) => {
    expect(isGreeting(text)).toBe(true);
  });

  it.each(["Hi, one of my employees hasn't come in for three days.", "Thanks", "Hello can I dismiss him?"])("%s is not", (text) => {
    expect(isGreeting(text)).toBe(false);
  });

  it("answers a greeting without opening a case (Ask without the AI gateway)", () => {
    const fetcher = vi.fn();
    render(<AskWorkspace companyId={COMPANY_ID} fetcher={fetcher as unknown as typeof fetch} mode="ready" returning={false} />);
    const box = screen.getByRole("textbox", { name: "Explain the situation in your own words" });
    fireEvent.change(box, { target: { value: "Hi Hannah" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByRole("status")).toHaveTextContent("Hi! What can HR help you with today?");
    expect(fetcher).not.toHaveBeenCalled();
    expect(box).toHaveValue("");
  });
});

describe("the status's workflow position", () => {
  const detail = (position: unknown) => ({
    conversation: {
      id: "9b1f3c3e-6a52-4b8f-9d0a-2c1e5f6a7b8c",
      title: "Disciplinary case · 22 Oct",
      case: { id: CASE_ID, title: "Disciplinary case · 22 Oct" },
      createdAt: "2026-10-22T10:00:00Z",
      updatedAt: "2026-10-22T10:00:00Z",
      revision: 2,
      status: {
        lifecycle: "in_progress",
        workflow: { key: "disciplinary", title: "Disciplinary" },
        attention: { needsInformation: false, jurisdiction: null, expertReview: { active: false, scope: null, actions: [], serviceAvailable: false } },
        checks: "ready",
        latestOutcome: "guidance",
        ...(position === undefined ? {} : { position }),
      },
    },
    messages: [],
    nextBefore: null,
  });

  it("reads the employer's recorded position, and an API from before M2-NEW-08 as none", () => {
    const position = { state: "in_stage", label: "Stage in progress", pathway: "Serious misconduct", stage: "Investigation", stageInProgress: true, heldSteps: [] };
    expect(parseConversationDetail(detail(position))?.conversation.status.position).toEqual(position);
    expect(parseConversationDetail(detail(undefined))?.conversation.status.position).toBeNull();
    expect(parseConversationDetail(detail({ ...position, extra: 1 }))).toBeNull();
  });
});
