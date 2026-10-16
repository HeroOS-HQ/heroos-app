import { parseWorkflowView, type WorkflowView } from "@/lib/workflows/model";

import { COMPANY_ID } from "./fixtures";

/**
 * Synthetic workflow data, shaped exactly like the HeroOS API's JSON (M2-01
 * with the M2-02 intake). Step availability, follow-ups and missing or
 * uncertain answers follow the API's rules; holds, cautions and the status are
 * given explicitly by each test (the web app never computes them).
 */

export const CASE_ID = "c4e0a000-0000-4000-8000-0000000000c1";
export const OTHER_CASE_ID = "c4e0a000-0000-4000-8000-0000000000c2";
export const NARRATIVE = "[SYNTHETIC] A team member left the site early on two shifts.";

const YES_NO = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "not_sure", label: "Not sure" },
];

type ApiQuestion = {
  key: string;
  kind: "text" | "date" | "choice";
  prompt: string;
  label: string;
  help: string | null;
  options: { value: string; label: string }[];
  max_length: number | null;
  allow_not_sure: boolean;
  ask_when: { key: string; values: string[] } | null;
};

const choice = (key: string, prompt: string, label: string, extra: Partial<ApiQuestion> = {}): ApiQuestion => ({
  key,
  kind: "choice",
  prompt,
  label,
  help: null,
  options: YES_NO,
  max_length: null,
  allow_not_sure: false,
  ask_when: null,
  ...extra,
});

const INITIAL: ApiQuestion[] = [
  {
    key: "incident.narrative",
    kind: "text",
    prompt: "What happened?",
    label: "What happened",
    help: "Describe the incident in your own words.",
    options: [],
    max_length: 4000,
    allow_not_sure: false,
    ask_when: null,
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
    ask_when: null,
  },
  choice("incident.history", "Is this a new issue, or has it been raised before?", "New or previously raised", {
    options: [
      { value: "new", label: "This is a new issue" },
      { value: "raised_before", label: "It has been raised before" },
      { value: "not_sure", label: "Not sure" },
    ],
  }),
  choice("incident.discussed_with_employee", "Has the matter already been discussed with the employee?", "Discussed with the employee"),
  choice("incident.evidence_available", "Is any supporting evidence available?", "Supporting evidence", {
    help: "You can't upload anything yet.",
  }),
];

const CONTEXT: ApiQuestion[] = [
  choice("context.location", "Did the incident happen at work, or while the employee was carrying out work duties?", "At work or outside work", {
    options: [
      { value: "at_work", label: "Yes, at work or while working" },
      { value: "outside_work", label: "No, outside work" },
      { value: "not_sure", label: "Not sure" },
    ],
  }),
  choice("context.work_connection", "Is the conduct connected to work in any way?", "Connection to work", {
    ask_when: { key: "context.location", values: ["outside_work"] },
  }),
  choice("history.documented_action", "Was the earlier action on this issue documented in writing?", "Earlier action documented", {
    options: [
      { value: "yes", label: "Yes, in writing" },
      { value: "verbal_only", label: "No, it was only raised verbally" },
      { value: "not_sure", label: "Not sure" },
    ],
    ask_when: { key: "incident.history", values: ["raised_before"] },
  }),
  choice("history.same_incident_sanction", "Has a disciplinary sanction already been issued for this same incident?", "Earlier sanction for this incident"),
  choice("context.policy_awareness", "Had the employee been told what was expected of them?", "Expected standard explained"),
  choice("evidence.witnesses", "Did anyone witness the incident?", "Witnesses"),
];

const SCREENING: ApiQuestion[] = [
  ["recent_complaint", "Has the employee recently complained to MOHRE or to the company's management?", "Recent complaint by the employee"],
  ["harassment_concern", "Has the employee raised a concern about harassment, bullying or discrimination?", "Harassment or discrimination concern"],
  ["pregnancy_maternity", "Is the employee pregnant or on maternity leave?", "Pregnancy or maternity leave"],
  ["sick_leave", "Is the employee currently on sick leave?", "Sick leave"],
  ["medical_condition", "Does the employee have a medical condition that you know of?", "Medical condition"],
  ["whistleblower", "Has the employee reported wrongdoing in the company (whistleblowing)?", "Whistleblowing"],
  ["senior_employee", "Is the employee in a senior role?", "Senior role"],
  ["criminal_allegation", "Is the employee involved in an allegation that could be a criminal matter?", "Possible criminal allegation"],
  ["dismissal_without_notice", "Are you considering dismissing the employee without notice?", "Dismissal without notice considered"],
].map(([key, prompt, label]) => choice(`screening.${key}`, prompt, label));

export const SCREENING_KEYS = SCREENING.map((q) => q.key);
export const ALL_CLEAR: Record<string, string> = Object.fromEntries(SCREENING_KEYS.map((key) => [key, "no"]));

const LABELS: Record<string, string> = { uae_federal: "UAE Federal (MOHRE)", difc: "DIFC" };

type Company = "uae_federal" | "difc" | null;

type Overrides = {
  answers?: Record<string, string>;
  revision?: number;
  canEdit?: boolean;
  /** The Company's operator-confirmed jurisdiction (null: not confirmed). */
  company?: Company;
  status?: { code: string; label: string };
  hold?: Record<string, unknown> | null;
  cautions?: Record<string, unknown>[];
  history?: Record<string, unknown>[];
  conversation?: unknown[];
  caseId?: string;
  escalation?: Record<string, unknown> | null;
  screening?: "disabled" | "synthetic_demo";
};

function jurisdictionOptions(company: Company) {
  return company
    ? [
        { value: company, label: `Yes, ${LABELS[company]}` },
        { value: "different", label: "No, a different jurisdiction applies" },
        { value: "not_sure", label: "Not sure" },
      ]
    : [];
}

export function apiView({
  answers = {},
  revision = 0,
  canEdit = true,
  company = null,
  status,
  hold,
  cautions = [],
  history,
  conversation,
  caseId = CASE_ID,
  escalation = null,
  screening = "synthetic_demo",
}: Overrides = {}): Record<string, unknown> {
  const caseAnswer = answers["jurisdiction.case_confirmation"];
  const resolved = company !== null && caseAnswer === company ? company : null;
  const steps = [
    { key: "initial_facts", title: "Initial facts", intro: "Let's start with what happened.", questions: INITIAL, available: true, unavailable_reason: null, provisional: false, sensitive: false },
    {
      key: "jurisdiction",
      title: "Employment jurisdiction",
      intro: "Please confirm which employment law applies to this employee.",
      questions: [
        choice("jurisdiction.case_confirmation", "Is this employee employed under your company's confirmed employment jurisdiction?", "Employment jurisdiction for this case", {
          options: jurisdictionOptions(company),
        }),
      ],
      available: company !== null,
      unavailable_reason: company !== null ? null : "Available once your company's employment jurisdiction is confirmed.",
      provisional: false,
      sensitive: false,
    },
    { key: "incident_context", title: "Incident context", intro: "A few more facts about the incident.", questions: CONTEXT, available: true, unavailable_reason: null, provisional: false, sensitive: false },
    {
      key: "safety_screening",
      title: "Safety screening",
      intro: "Some situations need specialist advice before any disciplinary step is taken.",
      questions: SCREENING,
      available: resolved === "uae_federal" && screening === "synthetic_demo",
      unavailable_reason:
        resolved === "uae_federal"
          ? screening === "synthetic_demo"
            ? null
            : "The safety screening isn't enabled in this environment."
          : resolved
            ? "Not available for this jurisdiction yet."
            : "Available once the case's jurisdiction is confirmed.",
      provisional: true,
      sensitive: true,
    },
  ];
  const asked = steps
    .filter((step) => step.available)
    .flatMap((step) => step.questions)
    .filter((q) => q.ask_when === null || q.ask_when.values.includes(answers[q.ask_when.key] ?? ""))
    .map((q) => q.key);
  const missing = asked.filter((key) => answers[key] === undefined);
  const uncertain = asked.filter((key) => answers[key] === "not_sure");
  const questions = steps.flatMap((step) => step.questions);
  const label = (key: string, value: string) =>
    questions.find((q) => q.key === key)?.options.find((o) => o.value === value)?.label ?? value;
  const defaultHold =
    company === null
      ? {
          kind: "hold",
          id: "hold",
          action: "block",
          reason: "company_jurisdiction_unconfirmed",
          title: "Paused: jurisdiction not confirmed",
          body: "Your company's employment jurisdiction hasn't been confirmed yet. Your answers stay saved.",
          items: [],
          provisional: false,
        }
      : null;
  const holdValue = hold === undefined ? defaultHold : hold;
  const answeredCount = asked.length - missing.length;
  const statusValue =
    status ??
    (holdValue
      ? holdValue.action === "escalate"
        ? { code: "held_for_specialist_review", label: "On hold: specialist review needed" }
        : { code: "awaiting_jurisdiction", label: "Awaiting jurisdiction confirmation" }
      : answeredCount === 0
        ? { code: "case_created", label: "Case created" }
        : missing.length > 0
          ? { code: "intake_in_progress", label: "Intake in progress" }
          : { code: "intake_recorded", label: "Intake recorded" });
  const stepProgress = (key: string) => {
    const keys = steps.find((s) => s.key === key)!.questions.map((q) => q.key).filter((k) => asked.includes(k));
    const done = keys.filter((k) => answers[k] !== undefined).length;
    return {
      key,
      label: steps.find((s) => s.key === key)!.title,
      status: done === 0 ? "needs_information" : done === keys.length ? "completed" : "in_progress",
      detail: done === keys.length ? `All ${keys.length} answered` : `${done} of ${keys.length} answered`,
    };
  };
  // A deep copy: tests may mutate it freely without affecting the shared questions.
  return structuredClone({
    case: {
      id: caseId,
      title: "[SYNTHETIC] Attendance concern",
      case_type: "disciplinary",
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:30:00Z",
    },
    workflow: { key: "disciplinary", title: "Disciplinary", definition_version: 2, revision },
    can_edit: canEdit,
    steps,
    answers,
    answer_labels: Object.fromEntries(Object.entries(answers).map(([key, value]) => [key, label(key, value)])),
    asked,
    missing,
    uncertain,
    progress: [
      { key: "case_created", label: "Case created", status: "completed", detail: "Saved" },
      stepProgress("initial_facts"),
      resolved
        ? { key: "jurisdiction", label: "Employment jurisdiction", status: "completed", detail: LABELS[resolved] }
        : { key: "jurisdiction", label: "Employment jurisdiction", status: company ? "needs_information" : "blocked", detail: "Not confirmed" },
      stepProgress("incident_context"),
      { key: "safety_screening", label: "Safety screening", status: resolved === "uae_federal" ? "needs_information" : "blocked", detail: "Not started" },
      { key: "next_stages", label: "Next stages", status: holdValue ? "blocked" : "coming_later", detail: holdValue ? "On hold" : "Not available yet" },
    ],
    status: statusValue,
    jurisdiction: {
      readiness: company ? "supported_confirmed" : "unconfirmed",
      reason: company ? "confirmed" : "licensing_not_provided",
      employment_jurisdiction: company,
      confirmed_at: company ? "2026-10-01T00:00:00Z" : null,
      guidance_allowed: company !== null,
    },
    intake: {
      case_jurisdiction: {
        status: resolved ? "resolved" : company === null ? "company_unconfirmed" : caseAnswer === undefined ? "awaiting_case_confirmation" : "case_not_sure",
        jurisdiction: resolved,
        label: resolved ? LABELS[resolved] : null,
        company_jurisdiction: company,
      },
      screening: resolved === "uae_federal" ? (screening === "synthetic_demo" ? "not_started" : "disabled") : "not_applicable",
      hold: holdValue,
      escalation,
      cautions,
      next_stage_open: statusValue.code === "intake_recorded",
    },
    sensitive_screening: screening,
    not_available: ["Classification of the incident", "Options and decisions", "Documents", "Expert review"],
    conversation: conversation ?? [
      { kind: "information", id: "welcome", title: "Welcome to your Disciplinary case", body: "This is a guided workflow, not an AI assistant." },
      {
        kind: "question_group",
        id: "step:initial_facts",
        step_key: "initial_facts",
        title: "Initial facts",
        body: "Let's start with what happened.",
        questions: INITIAL.map((q) => q.prompt),
      },
      ...(answeredCount > 0
        ? [
            {
              kind: "answer_confirmation",
              id: "submission:1",
              step_key: "initial_facts",
              submitted_at: "2026-10-15T09:30:00Z",
              by_viewer: true,
              items: Object.entries(answers).map(([key, value]) => ({
                key,
                label: questions.find((q) => q.key === key)!.label,
                display: label(key, value),
              })),
            },
            { kind: "status_notice", id: "saved:1", tone: "success", title: "Saved", body: "Your answers to “Initial facts” are saved." },
          ]
        : []),
      ...(holdValue ? [holdValue] : []),
      ...cautions,
      ...(missing.length > 0
        ? [
            {
              kind: "missing_information",
              id: "missing:initial_facts",
              step_key: "initial_facts",
              title: "Still to answer",
              body: "You can answer these now or come back to them later.",
              items: missing.map((key) => questions.find((q) => q.key === key)!.prompt),
            },
          ]
        : []),
      {
        kind: "status_notice",
        id: "next_stages",
        tone: "info",
        title: "What happens next",
        body: "Nothing in this case has been assessed or decided.",
      },
    ],
    history: history ?? [
      { id: "created", kind: "case_created", at: "2026-10-15T09:00:00Z", by_viewer: true, title: "Case created", detail: null },
    ],
  });
}

/** The parsed view the web app works with. */
export function view(overrides: Overrides = {}): WorkflowView {
  const parsed = parseWorkflowView(apiView(overrides));
  if (parsed === null) throw new Error("fixture does not parse");
  return parsed;
}

export const HIGH_RISK_HOLD = {
  kind: "hold",
  id: "hold",
  action: "escalate",
  reason: "high_risk_factors",
  title: "On hold: specialist review needed",
  body: "Your screening answers include a situation that needs specialist advice. HeroOS doesn't offer expert review in the app yet and hasn't contacted anyone about this case. Your answers stay saved.",
  items: ["Sick leave"],
  provisional: true,
};

export const EARLIER_HOLD = {
  kind: "hold",
  id: "hold",
  action: "escalate",
  reason: "earlier_escalation",
  title: "On hold: specialist review needed",
  body: "This case was held for specialist review because of an earlier answer. Changed answers are saved, but they don't release the hold, and HeroOS can't release it in the app yet.",
  items: ["First held because: a screening answer needed specialist advice"],
  provisional: true,
};

export const POLICY_CAUTION = {
  kind: "caution",
  id: "caution:policy_awareness",
  title: "Expected standard not explained",
  body: "You said the employee hadn't been told what was expected of them.",
  provisional: true,
};

export function apiCaseSummary(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: CASE_ID,
    title: "[SYNTHETIC] Attendance concern",
    case_type: "disciplinary",
    workflow_key: "disciplinary",
    status: { code: "case_created", label: "Case created" },
    answered: 0,
    total: 9,
    created_at: "2026-10-15T09:00:00Z",
    updated_at: "2026-10-15T09:30:00Z",
    ...overrides,
  };
}

export const WORKFLOW_CASES_PATH = `/companies/${COMPANY_ID}/workflows/disciplinary/cases`;
