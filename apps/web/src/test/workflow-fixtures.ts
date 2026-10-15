import { parseWorkflowView, type WorkflowView } from "@/lib/workflows/model";

import { COMPANY_ID } from "./fixtures";

/** Synthetic workflow data, shaped exactly like the HeroOS API's JSON (M2-01). */

export const CASE_ID = "c4e0a000-0000-4000-8000-0000000000c1";
export const OTHER_CASE_ID = "c4e0a000-0000-4000-8000-0000000000c2";
export const NARRATIVE = "[SYNTHETIC] A team member left the site early on two shifts.";

const QUESTIONS = [
  {
    key: "incident.narrative",
    kind: "text",
    prompt: "What happened?",
    label: "What happened",
    help: "Describe the incident in your own words.",
    options: [],
    max_length: 4000,
    allow_not_sure: false,
  },
  {
    key: "incident.date",
    kind: "date",
    prompt: "When did the incident happen?",
    label: "Date of the incident",
    help: "Choose “Not sure” if you don't know the exact date yet.",
    options: [],
    max_length: null,
    allow_not_sure: true,
  },
  {
    key: "incident.history",
    kind: "choice",
    prompt: "Is this a new issue, or has it been raised before?",
    label: "New or previously raised",
    help: null,
    options: [
      { value: "new", label: "This is a new issue" },
      { value: "raised_before", label: "It has been raised before" },
      { value: "not_sure", label: "Not sure" },
    ],
    max_length: null,
    allow_not_sure: false,
  },
  {
    key: "incident.discussed_with_employee",
    kind: "choice",
    prompt: "Has the matter already been discussed with the employee?",
    label: "Discussed with the employee",
    help: null,
    options: [
      { value: "yes", label: "Yes" },
      { value: "no", label: "No" },
      { value: "not_sure", label: "Not sure" },
    ],
    max_length: null,
    allow_not_sure: false,
  },
  {
    key: "incident.evidence_available",
    kind: "choice",
    prompt: "Is any supporting evidence available?",
    label: "Supporting evidence",
    help: "You can't upload anything yet.",
    options: [
      { value: "yes", label: "Yes" },
      { value: "no", label: "No" },
      { value: "not_sure", label: "Not sure" },
    ],
    max_length: null,
    allow_not_sure: false,
  },
];

type Overrides = {
  answers?: Record<string, string>;
  revision?: number;
  canEdit?: boolean;
  readiness?: "supported_confirmed" | "unconfirmed" | "unsupported";
  conversation?: unknown[];
  caseId?: string;
};

export function apiView({
  answers = {},
  revision = 0,
  canEdit = true,
  readiness = "unconfirmed",
  conversation,
  caseId = CASE_ID,
}: Overrides = {}): Record<string, unknown> {
  const missing = QUESTIONS.map((q) => q.key).filter((key) => answers[key] === undefined);
  const answered = QUESTIONS.length - missing.length;
  // A deep copy: tests may mutate it freely without affecting the shared questions.
  return structuredClone({
    case: {
      id: caseId,
      title: "[SYNTHETIC] Attendance concern",
      case_type: "disciplinary",
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:30:00Z",
    },
    workflow: { key: "disciplinary", title: "Disciplinary", definition_version: 1, revision },
    can_edit: canEdit,
    steps: [{ key: "initial_facts", title: "Initial facts", intro: "Let's start with what happened.", questions: QUESTIONS }],
    answers,
    missing,
    progress: [
      { key: "case_created", label: "Case created", status: "completed", detail: "Saved" },
      {
        key: "initial_facts",
        label: "Initial facts",
        status: answered === 0 ? "needs_information" : answered === QUESTIONS.length ? "completed" : "in_progress",
        detail: `${answered} of ${QUESTIONS.length} answered`,
      },
      {
        key: "jurisdiction",
        label: "Jurisdiction",
        status: readiness === "supported_confirmed" ? "completed" : "blocked",
        detail: readiness === "supported_confirmed" ? "Confirmed" : "Awaiting confirmation",
      },
      { key: "next_stages", label: "Assessment, decisions and documents", status: "coming_later", detail: "Not available yet" },
    ],
    status: answered === 0 ? { code: "case_created", label: "Case created" } : { code: "initial_facts_in_progress", label: "Initial facts in progress" },
    jurisdiction: {
      readiness,
      reason: readiness === "supported_confirmed" ? "confirmed" : "licensing_not_provided",
      employment_jurisdiction: readiness === "supported_confirmed" ? "difc" : null,
      confirmed_at: readiness === "supported_confirmed" ? "2026-10-01T00:00:00Z" : null,
      guidance_allowed: readiness === "supported_confirmed",
    },
    not_available: ["Conditions and safeguard checks", "Legal assessment and jurisdiction-specific guidance", "Documents", "Expert review"],
    conversation: conversation ?? [
      { kind: "information", id: "welcome", title: "Welcome to your Disciplinary case", body: "This is a guided workflow, not an AI assistant." },
      {
        kind: "question_group",
        id: "step:initial_facts",
        step_key: "initial_facts",
        title: "Initial facts",
        body: "Let's start with what happened.",
        questions: QUESTIONS.map((q) => q.prompt),
      },
      ...(answered > 0
        ? [
            {
              kind: "answer_confirmation",
              id: "submission:1",
              step_key: "initial_facts",
              submitted_at: "2026-10-15T09:30:00Z",
              by_viewer: true,
              items: Object.entries(answers).map(([key, value]) => ({
                key,
                label: QUESTIONS.find((q) => q.key === key)!.label,
                display: value,
              })),
            },
            { kind: "status_notice", id: "saved:1", tone: "success", title: "Saved", body: `${answered} of 5 initial questions answered.` },
          ]
        : []),
      ...(missing.length > 0
        ? [
            {
              kind: "missing_information",
              id: "missing:initial_facts",
              step_key: "initial_facts",
              title: "Still to answer",
              body: "You can answer these now or come back to them later.",
              items: missing.map((key) => QUESTIONS.find((q) => q.key === key)!.prompt),
            },
          ]
        : []),
      {
        kind: "status_notice",
        id: "jurisdiction",
        tone: "caution",
        title: "Jurisdiction not confirmed yet",
        body: "HeroOS can't continue with any jurisdiction-specific guidance.",
      },
      {
        kind: "status_notice",
        id: "next_stages",
        tone: "info",
        title: "What happens next",
        body: "Nothing in this case has been assessed or decided.",
      },
    ],
  });
}

/** The parsed view the web app works with. */
export function view(overrides: Overrides = {}): WorkflowView {
  const parsed = parseWorkflowView(apiView(overrides));
  if (parsed === null) throw new Error("fixture does not parse");
  return parsed;
}

export function apiCaseSummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: CASE_ID,
    title: "[SYNTHETIC] Attendance concern",
    case_type: "disciplinary",
    workflow_key: "disciplinary",
    status: { code: "case_created", label: "Case created" },
    answered: 0,
    total: 5,
    created_at: "2026-10-15T09:00:00Z",
    updated_at: "2026-10-15T09:30:00Z",
    ...overrides,
  };
}

export const WORKFLOW_CASES_PATH = `/companies/${COMPANY_ID}/workflows/disciplinary/cases`;
