/**
 * Guided workflow Cases (M2-01, M2-02 intake): the shapes the web app works
 * with, and strict parsers for the HeroOS API's JSON. Client-safe (no server
 * imports): the same parsers check the API's answers on the web server and, in
 * the browser, the BFF's answers.
 *
 * Nothing here interprets an answer. Workflow state, progress, the Case
 * jurisdiction, holds, cautions and what HeroOS says come from the API; the
 * browser only renders them.
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
/** Asked only while another answer is one of `values` (decided by the API). */
export type AskWhen = { key: string; values: string[] };
export type Question = {
  key: string;
  kind: QuestionKind;
  prompt: string;
  label: string;
  help: string | null;
  options: { value: string; label: string }[];
  maxLength: number | null;
  allowNotSure: boolean;
  askWhen: AskWhen | null;
};
export type Step = {
  key: string;
  title: string;
  intro: string;
  questions: Question[];
  /** Answerable in the Case's current state (the API refuses saves otherwise). */
  available: boolean;
  unavailableReason: string | null;
  /** Its checks are development content still under legal review. */
  provisional: boolean;
  /** It asks sensitive (health-related) questions. */
  sensitive: boolean;
};
export type ProgressItem = { key: string; label: string; status: ProgressStatus; detail: string };
export type Jurisdiction = {
  readiness: Readiness;
  reason: string;
  employmentJurisdiction: string | null;
  confirmedAt: string | null;
  guidanceAllowed: boolean;
};

export type HoldReason =
  | "high_risk_factors"
  | "jurisdiction_different"
  | "jurisdiction_unsupported"
  | "screening_not_covered"
  | "earlier_escalation"
  | "company_jurisdiction_unconfirmed"
  | "case_jurisdiction_not_sure"
  | "case_jurisdiction_outdated";
export type HoldMessage = {
  kind: "hold";
  id: string;
  /** block: paused until the jurisdiction is confirmed; escalate: specialist review needed. */
  action: "block" | "escalate";
  reason: HoldReason;
  title: string;
  body: string;
  items: string[];
  provisional: boolean;
};
export type CautionMessage = { kind: "caution"; id: string; title: string; body: string; provisional: boolean };

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
  | { kind: "status_notice"; id: string; tone: "info" | "caution" | "success"; title: string; body: string }
  | CautionMessage
  | HoldMessage;

export type CaseJurisdictionStatus =
  | "resolved"
  | "company_unconfirmed"
  | "company_unsupported"
  | "awaiting_case_confirmation"
  | "case_not_sure"
  | "case_different"
  | "case_confirmation_outdated";
export type Screening = "not_applicable" | "disabled" | "not_started" | "incomplete" | "not_cleared" | "cleared" | "positive";
/** The Case's first specialist-review hold: kept whatever the answers say now. */
export type Escalation = { since: string; reason: string; current: boolean };
export type Intake = {
  caseJurisdiction: {
    status: CaseJurisdictionStatus;
    jurisdiction: "uae_federal" | "difc" | null;
    label: string | null;
    companyJurisdiction: "uae_federal" | "difc" | null;
  };
  /** The current answers' screening state (separate from an earlier escalation). */
  screening: Screening;
  hold: HoldMessage | null;
  escalation: Escalation | null;
  cautions: CautionMessage[];
  /** Later stages may start (server-side gate); never while held. */
  nextStageOpen: boolean;
};
export type HistoryKind =
  | "case_created"
  | "answers_saved"
  | "jurisdiction"
  | "hold_placed"
  | "hold_kept"
  | "hold_lifted"
  | "screening"
  | "caution"
  | "intake_recorded";
export type HistoryItem = {
  id: string;
  kind: HistoryKind;
  at: string;
  /** The viewer, another administrator, or not attributed. */
  byViewer: boolean | null;
  title: string;
  detail: string | null;
};

export type WorkflowView = {
  case: { id: string; title: string; caseType: string; createdAt: string; updatedAt: string };
  workflow: { key: string; title: string; definitionVersion: number; revision: number };
  /** The caller may create Cases and save answers (decided by the API from the role). */
  canEdit: boolean;
  steps: Step[];
  /** Saved answers by question key; unanswered questions are absent. */
  answers: Record<string, string>;
  /** How each saved answer reads back (option labels, readable dates). */
  answerLabels: Record<string, string>;
  /** Questions asked in the current state; a saved answer outside it is kept but ignored. */
  asked: string[];
  missing: string[];
  /** Asked questions answered "Not sure". */
  uncertain: string[];
  progress: ProgressItem[];
  status: CaseStatus;
  jurisdiction: Jurisdiction;
  intake: Intake;
  /** "synthetic_demo": this environment holds made-up demo data only. */
  sensitiveScreening: "disabled" | "synthetic_demo";
  notAvailable: string[];
  conversation: Message[];
  history: HistoryItem[];
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
const HOLD_REASONS = new Set<string>([
  "high_risk_factors",
  "jurisdiction_different",
  "jurisdiction_unsupported",
  "screening_not_covered",
  "earlier_escalation",
  "company_jurisdiction_unconfirmed",
  "case_jurisdiction_not_sure",
  "case_jurisdiction_outdated",
]);
const CASE_JURISDICTION = new Set<string>([
  "resolved",
  "company_unconfirmed",
  "company_unsupported",
  "awaiting_case_confirmation",
  "case_not_sure",
  "case_different",
  "case_confirmation_outdated",
]);
const SCREENING = new Set<string>(["not_applicable", "disabled", "not_started", "incomplete", "not_cleared", "cleared", "positive"]);
const HISTORY_KINDS = new Set<string>([
  "case_created",
  "answers_saved",
  "jurisdiction",
  "hold_placed",
  "hold_kept",
  "hold_lifted",
  "screening",
  "caution",
  "intake_recorded",
]);
const SUPPORTED = new Set<string>(["uae_federal", "difc"]);
const isTextRecord = (value: unknown): value is Record<string, string> =>
  isRecord(value) && Object.entries(value).every(([key, item]) => FACT_KEY.test(key) && isText(item));
const isFactKeys = (value: unknown): value is string[] => isTexts(value) && value.every((key) => FACT_KEY.test(key));

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

function parseAskWhen(value: unknown): AskWhen | null | undefined {
  if (value === null) return null;
  return isRecord(value) && isText(value.key) && FACT_KEY.test(value.key) && isTexts(value.values)
    ? { key: value.key, values: value.values }
    : undefined;
}

function parseQuestion(value: unknown): Question | null {
  if (!isRecord(value) || !Array.isArray(value.options)) return null;
  const askWhen = parseAskWhen(value.ask_when);
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
    typeof value.allow_not_sure !== "boolean" ||
    askWhen === undefined
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
    askWhen,
  };
}

function parseStep(value: unknown): Step | null {
  if (
    !isRecord(value) ||
    !isText(value.key) ||
    !isText(value.title) ||
    !isText(value.intro) ||
    !Array.isArray(value.questions) ||
    typeof value.available !== "boolean" ||
    !isOptionalText(value.unavailable_reason) ||
    typeof value.provisional !== "boolean" ||
    typeof value.sensitive !== "boolean"
  ) {
    return null;
  }
  const questions = value.questions.map(parseQuestion);
  if (!questions.every((question) => question !== null)) return null;
  return {
    key: value.key,
    title: value.title,
    intro: value.intro,
    questions: questions as Question[],
    available: value.available,
    unavailableReason: value.unavailable_reason,
    provisional: value.provisional,
    sensitive: value.sensitive,
  };
}

function parseCaution(value: unknown): CautionMessage | null {
  return isRecord(value) &&
    value.kind === "caution" &&
    isText(value.id) &&
    isText(value.title) &&
    isText(value.body) &&
    typeof value.provisional === "boolean"
    ? { kind: "caution", id: value.id, title: value.title, body: value.body, provisional: value.provisional }
    : null;
}

function parseHold(value: unknown): HoldMessage | null {
  return isRecord(value) &&
    value.kind === "hold" &&
    isText(value.id) &&
    (value.action === "block" || value.action === "escalate") &&
    isText(value.reason) &&
    HOLD_REASONS.has(value.reason) &&
    isText(value.title) &&
    isText(value.body) &&
    isTexts(value.items) &&
    typeof value.provisional === "boolean"
    ? {
        kind: "hold",
        id: value.id,
        action: value.action,
        reason: value.reason as HoldReason,
        title: value.title,
        body: value.body,
        items: value.items,
        provisional: value.provisional,
      }
    : null;
}

function parseIntake(value: unknown): Intake | null {
  if (!isRecord(value) || !isRecord(value.case_jurisdiction) || !Array.isArray(value.cautions)) return null;
  const jurisdiction = value.case_jurisdiction;
  const supportedOrNull = (item: unknown): item is "uae_federal" | "difc" | null =>
    item === null || (isText(item) && SUPPORTED.has(item));
  if (
    !isText(jurisdiction.status) ||
    !CASE_JURISDICTION.has(jurisdiction.status) ||
    !supportedOrNull(jurisdiction.jurisdiction) ||
    !isOptionalText(jurisdiction.label) ||
    !supportedOrNull(jurisdiction.company_jurisdiction) ||
    !isText(value.screening) ||
    !SCREENING.has(value.screening) ||
    typeof value.next_stage_open !== "boolean"
  ) {
    return null;
  }
  const hold = value.hold === null ? null : parseHold(value.hold);
  const cautions = value.cautions.map(parseCaution);
  const escalation = value.escalation;
  const validEscalation =
    escalation === null ||
    (isRecord(escalation) && isText(escalation.since) && isText(escalation.reason) && typeof escalation.current === "boolean");
  if ((value.hold !== null && hold === null) || !cautions.every((caution) => caution !== null) || !validEscalation) return null;
  // The gate is never open while the Case is held, whatever the payload says.
  return {
    caseJurisdiction: {
      status: jurisdiction.status as CaseJurisdictionStatus,
      jurisdiction: jurisdiction.jurisdiction,
      label: jurisdiction.label,
      companyJurisdiction: jurisdiction.company_jurisdiction,
    },
    screening: value.screening as Screening,
    hold,
    escalation: isRecord(escalation)
      ? { since: escalation.since as string, reason: escalation.reason as string, current: escalation.current as boolean }
      : null,
    cautions: cautions as CautionMessage[],
    nextStageOpen: value.next_stage_open && hold === null,
  };
}

function parseHistoryItem(value: unknown): HistoryItem | null {
  return isRecord(value) &&
    isText(value.id) &&
    isText(value.kind) &&
    HISTORY_KINDS.has(value.kind) &&
    isText(value.at) &&
    (value.by_viewer === null || typeof value.by_viewer === "boolean") &&
    isText(value.title) &&
    isOptionalText(value.detail)
    ? {
        id: value.id,
        kind: value.kind as HistoryKind,
        at: value.at,
        byViewer: value.by_viewer,
        title: value.title,
        detail: value.detail,
      }
    : null;
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
    case "caution":
      return parseCaution(value);
    case "hold":
      return parseHold(value);
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
    !isFactKeys(body.missing) ||
    !isFactKeys(body.asked) ||
    !isFactKeys(body.uncertain) ||
    !Array.isArray(body.progress) ||
    !isTexts(body.not_available) ||
    !Array.isArray(body.conversation) ||
    !Array.isArray(body.history) ||
    !isTextRecord(body.answers) ||
    !isTextRecord(body.answer_labels) ||
    (body.sensitive_screening !== "disabled" && body.sensitive_screening !== "synthetic_demo")
  ) {
    return null;
  }
  const steps = body.steps.map(parseStep);
  const progress = body.progress.map(parseProgress);
  const status = parseStatus(body.status);
  const jurisdiction = parseJurisdiction(body.jurisdiction);
  const intake = parseIntake(body.intake);
  const messages = body.conversation.map(parseMessage);
  const history = body.history.map(parseHistoryItem);
  if (
    !steps.every((step) => step !== null) ||
    !progress.every((item) => item !== null) ||
    status === null ||
    jurisdiction === null ||
    intake === null ||
    messages.some((message) => message === null) ||
    !history.every((item) => item !== null)
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
    answers: body.answers,
    answerLabels: body.answer_labels,
    asked: body.asked,
    missing: body.missing,
    uncertain: body.uncertain,
    progress: progress as ProgressItem[],
    status,
    jurisdiction,
    intake,
    sensitiveScreening: body.sensitive_screening,
    notAvailable: body.not_available,
    conversation: messages.filter((message): message is Message => message !== undefined && message !== null),
    history: history as HistoryItem[],
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
    Array.isArray(value.asked) &&
    Array.isArray(value.history) &&
    isRecord(value.answers) &&
    isRecord(value.answerLabels) &&
    isRecord(value.jurisdiction) &&
    isRecord(value.intake)
  );
}
