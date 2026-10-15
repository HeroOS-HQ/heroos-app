/**
 * Guided workflow Cases (M2-01): the shapes the web app works with, and strict
 * parsers for the HeroOS API's JSON. Client-safe (no server imports): the same
 * parsers check the API's answers on the web server and, in the browser, the
 * BFF's answers.
 *
 * Nothing here interprets an answer. Workflow state, progress and what HeroOS
 * says come from the API; the browser only renders them.
 */

export type ProgressStatus = "completed" | "in_progress" | "needs_information" | "blocked" | "coming_later";
export type Readiness = "supported_confirmed" | "unconfirmed" | "unsupported";
export type CaseStatus = { code: string; label: string };

export type CaseSummary = {
  id: string;
  title: string;
  caseType: string;
  workflowKey: string;
  status: CaseStatus;
  answered: number;
  total: number;
  createdAt: string;
  /** Last activity: creation or the latest saved answers. */
  updatedAt: string;
};

export type QuestionKind = "text" | "date" | "choice";
export type Question = {
  key: string;
  kind: QuestionKind;
  prompt: string;
  label: string;
  help: string | null;
  options: { value: string; label: string }[];
  maxLength: number | null;
  allowNotSure: boolean;
};
export type Step = { key: string; title: string; intro: string; questions: Question[] };
export type ProgressItem = { key: string; label: string; status: ProgressStatus; detail: string };
export type Jurisdiction = {
  readiness: Readiness;
  reason: string;
  employmentJurisdiction: string | null;
  confirmedAt: string | null;
  guidanceAllowed: boolean;
};

export type Message =
  | { kind: "information"; id: string; title: string; body: string }
  | { kind: "question_group"; id: string; stepKey: string; title: string; body: string; questions: string[] }
  | {
      kind: "answer_confirmation";
      id: string;
      stepKey: string;
      submittedAt: string;
      byViewer: boolean;
      items: { key: string; label: string; display: string | null }[];
    }
  | { kind: "missing_information"; id: string; stepKey: string; title: string; body: string; items: string[] }
  | { kind: "status_notice"; id: string; tone: "info" | "caution" | "success"; title: string; body: string };

export type WorkflowView = {
  case: { id: string; title: string; caseType: string; createdAt: string; updatedAt: string };
  workflow: { key: string; title: string; definitionVersion: number; revision: number };
  /** The caller may create Cases and save answers (decided by the API from the role). */
  canEdit: boolean;
  steps: Step[];
  /** Current answers by question key; unanswered questions are absent. */
  answers: Record<string, string>;
  missing: string[];
  progress: ProgressItem[];
  status: CaseStatus;
  jurisdiction: Jurisdiction;
  notAvailable: string[];
  conversation: Message[];
};

export const WORKFLOW_DISCIPLINARY = "disciplinary";
export const NOT_SURE = "not_sure";
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** Workflow and step keys, as path segments. */
export const KEY = /^[a-z][a-z_]{0,49}$/;
/** Question (fact) keys. */
export const FACT_KEY = /^[a-z][a-z_.]{0,99}$/;
export const TITLE_MAX = 200;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string";
const isOptionalText = (value: unknown): value is string | null => value === null || typeof value === "string";
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isTexts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const isId = (value: unknown): value is string => typeof value === "string" && UUID.test(value);

const PROGRESS = new Set<string>(["completed", "in_progress", "needs_information", "blocked", "coming_later"]);
const READINESS = new Set<string>(["supported_confirmed", "unconfirmed", "unsupported"]);
const KINDS = new Set<string>(["text", "date", "choice"]);
const TONES = new Set<string>(["info", "caution", "success"]);

function parseStatus(value: unknown): CaseStatus | null {
  return isRecord(value) && isText(value.code) && isText(value.label) ? { code: value.code, label: value.label } : null;
}

export function parseCaseSummary(body: unknown): CaseSummary | null {
  if (!isRecord(body)) return null;
  const status = parseStatus(body.status);
  if (
    !isId(body.id) ||
    !isText(body.title) ||
    !isText(body.case_type) ||
    !isText(body.workflow_key) ||
    status === null ||
    !isCount(body.answered) ||
    !isCount(body.total) ||
    !isText(body.created_at) ||
    !isText(body.updated_at)
  ) {
    return null;
  }
  return {
    id: body.id,
    title: body.title,
    caseType: body.case_type,
    workflowKey: body.workflow_key,
    status,
    answered: body.answered,
    total: body.total,
    createdAt: body.created_at,
    updatedAt: body.updated_at,
  };
}

export function parseCaseSummaries(body: unknown): CaseSummary[] | null {
  if (!Array.isArray(body)) return null;
  const cases = body.map(parseCaseSummary);
  return cases.every((item): item is CaseSummary => item !== null) ? cases : null;
}

function parseQuestion(value: unknown): Question | null {
  if (!isRecord(value) || !Array.isArray(value.options)) return null;
  const options = value.options.map((option) =>
    isRecord(option) && isText(option.value) && isText(option.label) ? { value: option.value, label: option.label } : null,
  );
  if (
    !isText(value.key) ||
    !FACT_KEY.test(value.key) ||
    !isText(value.kind) ||
    !KINDS.has(value.kind) ||
    !isText(value.prompt) ||
    !isText(value.label) ||
    !isOptionalText(value.help) ||
    !options.every((option) => option !== null) ||
    !(value.max_length === null || isCount(value.max_length)) ||
    typeof value.allow_not_sure !== "boolean"
  ) {
    return null;
  }
  return {
    key: value.key,
    kind: value.kind as QuestionKind,
    prompt: value.prompt,
    label: value.label,
    help: value.help,
    options: options as { value: string; label: string }[],
    maxLength: value.max_length as number | null,
    allowNotSure: value.allow_not_sure,
  };
}

function parseStep(value: unknown): Step | null {
  if (!isRecord(value) || !isText(value.key) || !isText(value.title) || !isText(value.intro) || !Array.isArray(value.questions)) {
    return null;
  }
  const questions = value.questions.map(parseQuestion);
  if (!questions.every((question) => question !== null)) return null;
  return { key: value.key, title: value.title, intro: value.intro, questions: questions as Question[] };
}

function parseProgress(value: unknown): ProgressItem | null {
  if (!isRecord(value) || !isText(value.key) || !isText(value.label) || !isText(value.status) || !PROGRESS.has(value.status) || !isText(value.detail)) {
    return null;
  }
  return { key: value.key, label: value.label, status: value.status as ProgressStatus, detail: value.detail };
}

function parseJurisdiction(value: unknown): Jurisdiction | null {
  if (
    !isRecord(value) ||
    !isText(value.readiness) ||
    !READINESS.has(value.readiness) ||
    !isText(value.reason) ||
    !isOptionalText(value.employment_jurisdiction) ||
    !isOptionalText(value.confirmed_at) ||
    typeof value.guidance_allowed !== "boolean"
  ) {
    return null;
  }
  const readiness = value.readiness as Readiness;
  return {
    readiness,
    reason: value.reason,
    employmentJurisdiction: value.employment_jurisdiction,
    confirmedAt: value.confirmed_at,
    // Guidance only ever follows a supported, confirmed jurisdiction.
    guidanceAllowed: readiness === "supported_confirmed" && value.guidance_allowed,
  };
}

/** One conversation message; `undefined` for a kind this version doesn't know (skipped). */
function parseMessage(value: unknown): Message | null | undefined {
  if (!isRecord(value) || !isText(value.kind) || !isText(value.id)) return null;
  const { kind, id } = value;
  switch (kind) {
    case "information":
      return isText(value.title) && isText(value.body) ? { kind, id, title: value.title, body: value.body } : null;
    case "question_group":
      return isText(value.step_key) && isText(value.title) && isText(value.body) && isTexts(value.questions)
        ? { kind, id, stepKey: value.step_key, title: value.title, body: value.body, questions: value.questions }
        : null;
    case "answer_confirmation": {
      if (!isText(value.step_key) || !isText(value.submitted_at) || typeof value.by_viewer !== "boolean" || !Array.isArray(value.items)) {
        return null;
      }
      const items = value.items.map((item) =>
        isRecord(item) && isText(item.key) && isText(item.label) && isOptionalText(item.display)
          ? { key: item.key, label: item.label, display: item.display }
          : null,
      );
      if (!items.every((item) => item !== null)) return null;
      return {
        kind,
        id,
        stepKey: value.step_key,
        submittedAt: value.submitted_at,
        byViewer: value.by_viewer,
        items: items as { key: string; label: string; display: string | null }[],
      };
    }
    case "missing_information":
      return isText(value.step_key) && isText(value.title) && isText(value.body) && isTexts(value.items)
        ? { kind, id, stepKey: value.step_key, title: value.title, body: value.body, items: value.items }
        : null;
    case "status_notice":
      return isText(value.tone) && TONES.has(value.tone) && isText(value.title) && isText(value.body)
        ? { kind, id, tone: value.tone as "info" | "caution" | "success", title: value.title, body: value.body }
        : null;
    default:
      // A newer API may add message kinds (decisions, documents, ...): skip them
      // rather than break the page; this version can't render them anyway.
      return undefined;
  }
}

export function parseWorkflowView(body: unknown): WorkflowView | null {
  if (!isRecord(body) || !isRecord(body.case) || !isRecord(body.workflow) || !isRecord(body.answers)) return null;
  const { workflow } = body;
  const record = body.case;
  if (
    !isId(record.id) ||
    !isText(record.title) ||
    !isText(record.case_type) ||
    !isText(record.created_at) ||
    !isText(record.updated_at) ||
    !isText(workflow.key) ||
    !isText(workflow.title) ||
    !isCount(workflow.definition_version) ||
    !isCount(workflow.revision) ||
    typeof body.can_edit !== "boolean" ||
    !Array.isArray(body.steps) ||
    !isTexts(body.missing) ||
    !Array.isArray(body.progress) ||
    !isTexts(body.not_available) ||
    !Array.isArray(body.conversation) ||
    !Object.entries(body.answers).every(([key, value]) => FACT_KEY.test(key) && isText(value))
  ) {
    return null;
  }
  const steps = body.steps.map(parseStep);
  const progress = body.progress.map(parseProgress);
  const status = parseStatus(body.status);
  const jurisdiction = parseJurisdiction(body.jurisdiction);
  const messages = body.conversation.map(parseMessage);
  if (
    !steps.every((step) => step !== null) ||
    !progress.every((item) => item !== null) ||
    status === null ||
    jurisdiction === null ||
    messages.some((message) => message === null)
  ) {
    return null;
  }
  return {
    case: {
      id: record.id,
      title: record.title,
      caseType: record.case_type,
      createdAt: record.created_at,
      updatedAt: record.updated_at,
    },
    workflow: {
      key: workflow.key,
      title: workflow.title,
      definitionVersion: workflow.definition_version,
      revision: workflow.revision,
    },
    canEdit: body.can_edit,
    steps: steps as Step[],
    answers: body.answers as Record<string, string>,
    missing: body.missing,
    progress: progress as ProgressItem[],
    status,
    jurisdiction,
    notAvailable: body.not_available,
    conversation: messages.filter((message): message is Message => message !== undefined && message !== null),
  };
}

/** A BFF answer in the browser: the same view the server rendered, for the same Case. */
export function isWorkflowView(value: unknown, caseId: string): value is WorkflowView {
  if (!isRecord(value) || !isRecord(value.case) || !isRecord(value.workflow)) return false;
  return (
    value.case.id === caseId &&
    isCount(value.workflow.revision) &&
    typeof value.canEdit === "boolean" &&
    Array.isArray(value.steps) &&
    Array.isArray(value.conversation) &&
    Array.isArray(value.progress) &&
    isRecord(value.answers) &&
    isRecord(value.jurisdiction)
  );
}
