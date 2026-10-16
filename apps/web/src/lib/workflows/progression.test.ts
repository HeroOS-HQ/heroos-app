import { describe, expect, it } from "vitest";

import {
  apiProgression,
  apiView,
  CHECKLIST,
  CHOSEN,
  inStageProgression,
  message,
  pathwayOptions,
  transition,
} from "@/test/workflow-fixtures";

import { parseWorkflowView } from "./model";
import { checklistStep, parseProgression } from "./progression";
import { parsePathwayRequest, parseTransitionRequest } from "./requests";

const REQUEST_KEY = "a1b2c3d4-0000-4000-8000-0000000000cc";

describe("parseProgression", () => {
  it("reads an API without progression as nothing to progress", () => {
    const parsed = parseWorkflowView(apiView());
    expect(parsed).not.toBeNull();
    expect(parsed!.progression).toBeNull();
  });

  it("parses the awaiting-pathway state with the synthetic-rules notice", () => {
    const parsed = parseWorkflowView(apiView({ progression: apiProgression() }))!;
    const progression = parsed.progression!;
    expect(progression.status).toEqual({ code: "awaiting_pathway", label: "Choose a pathway" });
    expect(progression.rules).toMatchObject({ provenance: "synthetic", notice: { title: "Synthetic test rules" } });
    expect(progression.pathwayOptions.map((option) => [option.key, option.transition?.allowed])).toEqual([
      ["less_serious", true],
      ["serious", true],
      ["undetermined", true],
    ]);
    expect(progression.pathwayOptions[2].unlocksStages).toBe(false);
  });

  it("never offers a transition the decision refuses, whatever the flag says", () => {
    const forged = inStageProgression({
      actions: [
        transition("complete:test_check_in", "Mark complete", { decision: "block", allowed: true }),
        transition("start:test_written_note", "Start", { decision: "escalate", allowed: true, acknowledge: ["x"] }),
      ],
    });
    const progression = parseProgression(forged)!;
    expect(progression.actions.map((action) => action.allowed)).toEqual([false, false]);
    expect(progression.actions[1].acknowledge).toEqual([]);
  });

  it("offers nothing while a gate applies to the whole case", () => {
    const gated = inStageProgression({
      gate: { code: "case_held", title: "On hold: specialist review needed", body: "Test." },
      actions: [transition("complete:test_check_in", "Mark complete", { decision: "allow", allowed: true })],
      pathway_options: pathwayOptions("less_serious", { serious: { allowed: true } }),
    });
    const progression = parseProgression(gated)!;
    expect(progression.actions.every((action) => !action.allowed)).toBe(true);
    expect(progression.pathwayOptions.every((option) => !option.transition?.allowed)).toBe(true);
    expect(progression.checklist).toBeNull();
  });

  it("keeps acknowledgments only for a warned transition, and pathway transitions out of the stage actions", () => {
    const progression = parseProgression(
      apiProgression({
        actions: [
          transition("pathway:serious", "Record pathway"),
          transition("start:test_check_in", "Start", {
            decision: "warn",
            warnings: [message("test_caution", "warn", "Test caution")],
            acknowledge: ["test_caution"],
          }),
        ],
      }),
    )!;
    expect(progression.actions.map((action) => action.key)).toEqual(["start:test_check_in"]);
    expect(progression.actions[0].acknowledge).toEqual(["test_caution"]);
  });

  it.each([
    ["an unknown decision", { actions: [transition("start:test_check_in", "Start", { decision: "approve" as never })] }],
    ["a malformed transition key", { actions: [transition("skip:test_check_in", "Skip")] }],
    ["a stage status out of the vocabulary", { stages: [{ key: "a", title: "A", summary: "A", optional: false, terminal: false, status: "skipped" }] }],
    ["a bad provenance", { rules: { bundle: "b", version: "1", provenance: "official", notice: null } }],
    ["a non-boolean flag", { actions: [transition("start:test_check_in", "Start", { allowed: "yes" as never })] }],
  ])("refuses the whole view for %s", (_, overrides) => {
    expect(parseWorkflowView(apiView({ progression: apiProgression(overrides) }))).toBeNull();
  });

  it("turns the checklist into a step the answers form can save", () => {
    const progression = parseProgression(inStageProgression({ pathway: CHOSEN }))!;
    const step = checklistStep(progression.checklist!);
    expect(step.key).toBe(CHECKLIST.step_key);
    expect(step.questions.map((question) => [question.key, question.kind])).toEqual([
      ["progress.test_check_in.conversation_held", "choice"],
      ["progress.test_check_in.employee_heard", "choice"],
    ]);
    expect(step.available).toBe(true);
  });
});

describe("progression request parsers", () => {
  it("rebuilds a pathway request field by field", () => {
    expect(parsePathwayRequest({ expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "less_serious" })).toEqual({
      ok: true,
      value: { expected_revision: 4, request_key: REQUEST_KEY, pathway: "less_serious", acknowledged_warnings: [] },
    });
    expect(
      parsePathwayRequest({ expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "serious", acknowledgedWarnings: ["a_b"] }),
    ).toMatchObject({ ok: true, value: { acknowledged_warnings: ["a_b"] } });
  });

  it.each([
    { expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "less_serious", extra: true },
    { expectedRevision: -1, requestKey: REQUEST_KEY, pathway: "less_serious" },
    { expectedRevision: 4, requestKey: "not-a-uuid", pathway: "less_serious" },
    { expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "Less Serious" },
    { expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "less_serious", acknowledgedWarnings: ["Not a code"] },
    { expectedRevision: 4, requestKey: REQUEST_KEY, pathway: "less_serious", acknowledgedWarnings: ["a", "a"] },
    { expectedRevision: 4, requestKey: REQUEST_KEY, transition: "start:test_check_in" },
  ])("refuses a malformed pathway request %#", (body) => {
    expect(parsePathwayRequest(body)).toEqual({ ok: false });
  });

  it("accepts only stage transitions, never a pathway or an unknown verb", () => {
    expect(
      parseTransitionRequest({ expectedRevision: 2, requestKey: REQUEST_KEY, transition: "complete:test_check_in" }),
    ).toMatchObject({ ok: true, value: { transition: "complete:test_check_in" } });
    for (const transition of ["pathway:serious", "approve:test_check_in", "start:", "start:Test", "start:a b"]) {
      expect(parseTransitionRequest({ expectedRevision: 2, requestKey: REQUEST_KEY, transition }), transition).toEqual({ ok: false });
    }
  });
});
