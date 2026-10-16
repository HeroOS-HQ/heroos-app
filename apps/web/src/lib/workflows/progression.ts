import { FACT_KEY, KEY, type Step, UUID } from "./model";

/**
 * Workflow progression (M2-03): the shapes and a strict parser for the view's
 * `progression` block. Client-safe. Everything here is what the HeroOS API
 * decided from its installed rules; the browser only renders it, and only
 * offers what the API says it would accept. Nothing is computed here.
 */

export type ProgressDecision = "allow" | "warn" | "block" | "escalate";
export type ProgressAction = "warn" | "block" | "escalate";
export type ProgressMessage = {
  /** An engine code or a rule key (stable; never an answer). */
  code: string;
  action: ProgressAction;
  source: "engine" | "bundle";
  title: string;
  body: string;
  /** Content still under review: never presented as approved advice. */
  provisional: boolean;
};
export type ProgressTransition = {
  /** Sent back to request this transition. */
  key: string;
  kind: "pathway" | "start" | "complete";
  label: string;
  decision: ProgressDecision;
  /** The API would apply it now (with `acknowledge` acknowledged). */
  allowed: boolean;
  reasons: ProgressMessage[];
  warnings: ProgressMessage[];
  /** Warning codes that must be acknowledged, exactly. */
  acknowledge: string[];
  /** Labels of missing or "Not sure" answers behind a refusal. */
  missing: string[];
};
export type PathwayOption = {
  key: string;
  label: string;
  description: string;
  /** False: recorded like any choice, but never opens a stage. */
  unlocksStages: boolean;
  current: boolean;
  transition: ProgressTransition | null;
};
export type PathwayChoice = {
  key: string;
  label: string;
  description: string;
  decidedAt: string;
  byViewer: boolean;
  previous: string | null;
};
export type StageStatus = "completed" | "in_progress" | "next" | "later";
export type ProgressStage = {
  key: string;
  title: string;
  summary: string;
  optional: boolean;
  terminal: boolean;
  status: StageStatus;
};
export type ChecklistQuestion = {
  key: string;
  prompt: string;
  label: string;
  help: string | null;
  options: { value: string; label: string }[];
};
export type Checklist = { stepKey: string; title: string; intro: string; questions: ChecklistQuestion[] };
export type ProgressAttempt = {
  requestKey: string;
  transition: string;
  label: string;
  outcome: "applied" | "rejected";
  decision: ProgressDecision;
  title: string;
  body: string;
};
export type ProgressHistoryKind =
  | "pathway_selected"
  | "stage_started"
  | "stage_completed"
  | "transition_rejected"
  | "escalation_recorded";
export type ProgressHistoryItem = {
  id: string;
  kind: ProgressHistoryKind;
  at: string;
  byViewer: boolean;
  title: string;
  detail: string | null;
};
export type Progression = {
  status: { code: string; label: string };
  /** Applies to every transition (null: progression is open). */
  gate: { code: string; title: string; body: string } | null;
  rules: { bundle: string; version: string; provenance: "synthetic" | "private"; notice: ProgressMessage | null } | null;
  pathway: PathwayChoice | null;
  pathwayOptions: PathwayOption[];
  stages: ProgressStage[];
  actions: ProgressTransition[];
  checklist: Checklist | null;
  /** Recorded needs for specialist review: unresolved (no release exists). */
  escalations: { transition: string; label: string; since: string }[];
  notAvailable: string[];
  history: ProgressHistoryItem[];
  attempt: ProgressAttempt | null;
};

/** Transition keys as the API offers them. */
export const TRANSITION_KEY = /^(pathway|start|complete):[a-z][a-z_]{0,49}$/;
/** Rule and engine codes (warnings to acknowledge). */
export const CODE = /^[a-z][a-z_]{0,59}$/;

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string";
const isOptionalText = (value: unknown): value is string | null => value === null || typeof value === "string";
const isTexts = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText);
const isBool = (value: unknown): value is boolean => typeof value === "boolean";
const DECISIONS = new Set<string>(["allow", "warn", "block", "escalate"]);
const ACTIONS = new Set<string>(["warn", "block", "escalate"]);
const KINDS = new Set<string>(["pathway", "start", "complete"]);
const STAGE_STATUSES = new Set<string>(["completed", "in_progress", "next", "later"]);
const HISTORY_KINDS = new Set<string>([
  "pathway_selected",
  "stage_started",
  "stage_completed",
  "transition_rejected",
  "escalation_recorded",
]);

function list<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(parse);
  return items.every((item) => item !== null) ? (items as T[]) : null;
}

function parseMessage(value: unknown): ProgressMessage | null {
  return isRecord(value) &&
    isText(value.code) &&
    isText(value.action) &&
    ACTIONS.has(value.action) &&
    (value.source === "engine" || value.source === "bundle") &&
    isText(value.title) &&
    isText(value.body) &&
    isBool(value.provisional)
    ? {
        code: value.code,
        action: value.action as ProgressAction,
        source: value.source,
        title: value.title,
        body: value.body,
        provisional: value.provisional,
      }
    : null;
}

function parseTransition(value: unknown): ProgressTransition | null {
  if (!isRecord(value)) return null;
  const reasons = list(value.reasons, parseMessage);
  const warnings = list(value.warnings, parseMessage);
  if (
    !isText(value.key) ||
    !TRANSITION_KEY.test(value.key) ||
    !isText(value.kind) ||
    !KINDS.has(value.kind) ||
    !isText(value.label) ||
    !isText(value.decision) ||
    !DECISIONS.has(value.decision) ||
    !isBool(value.allowed) ||
    reasons === null ||
    warnings === null ||
    !isTexts(value.acknowledge) ||
    !value.acknowledge.every((code) => CODE.test(code)) ||
    !isTexts(value.missing)
  ) {
    return null;
  }
  const decision = value.decision as ProgressDecision;
  return {
    key: value.key,
    kind: value.kind as ProgressTransition["kind"],
    label: value.label,
    decision,
    // Never offered when the decision refuses it, whatever the flag says.
    allowed: value.allowed && (decision === "allow" || decision === "warn"),
    reasons,
    warnings,
    acknowledge: decision === "warn" ? value.acknowledge : [],
    missing: value.missing,
  };
}

function parseOption(value: unknown): PathwayOption | null {
  if (!isRecord(value)) return null;
  const transition = value.transition === null ? null : parseTransition(value.transition);
  if (
    !isText(value.key) ||
    !KEY.test(value.key) ||
    !isText(value.label) ||
    !isText(value.description) ||
    !isBool(value.unlocks_stages) ||
    !isBool(value.current) ||
    (value.transition !== null && transition === null)
  ) {
    return null;
  }
  return {
    key: value.key,
    label: value.label,
    description: value.description,
    unlocksStages: value.unlocks_stages,
    current: value.current,
    transition: transition && transition.kind === "pathway" ? transition : null,
  };
}

function parseChoice(value: unknown): PathwayChoice | null | undefined {
  if (value === null) return null;
  return isRecord(value) &&
    isText(value.key) &&
    isText(value.label) &&
    isText(value.description) &&
    isText(value.decided_at) &&
    isBool(value.by_viewer) &&
    isOptionalText(value.previous)
    ? {
        key: value.key,
        label: value.label,
        description: value.description,
        decidedAt: value.decided_at,
        byViewer: value.by_viewer,
        previous: value.previous,
      }
    : undefined;
}

function parseStage(value: unknown): ProgressStage | null {
  return isRecord(value) &&
    isText(value.key) &&
    KEY.test(value.key) &&
    isText(value.title) &&
    isText(value.summary) &&
    isBool(value.optional) &&
    isBool(value.terminal) &&
    isText(value.status) &&
    STAGE_STATUSES.has(value.status)
    ? {
        key: value.key,
        title: value.title,
        summary: value.summary,
        optional: value.optional,
        terminal: value.terminal,
        status: value.status as StageStatus,
      }
    : null;
}

function parseChecklistQuestion(value: unknown): ChecklistQuestion | null {
  if (!isRecord(value) || !isText(value.key) || !FACT_KEY.test(value.key) || !Array.isArray(value.options)) return null;
  const options = value.options.map((option) =>
    isRecord(option) && isText(option.value) && isText(option.label) ? { value: option.value, label: option.label } : null,
  );
  return isText(value.prompt) && isText(value.label) && isOptionalText(value.help) && options.every((o) => o !== null)
    ? {
        key: value.key,
        prompt: value.prompt,
        label: value.label,
        help: value.help,
        options: options as { value: string; label: string }[],
      }
    : null;
}

function parseChecklist(value: unknown): Checklist | null | undefined {
  if (value === null) return null;
  if (!isRecord(value) || !isText(value.step_key) || !KEY.test(value.step_key) || !isText(value.title) || !isText(value.intro)) {
    return undefined;
  }
  const questions = list(value.questions, parseChecklistQuestion);
  return questions === null ? undefined : { stepKey: value.step_key, title: value.title, intro: value.intro, questions };
}

function parseAttempt(value: unknown): ProgressAttempt | null | undefined {
  if (value === null) return null;
  return isRecord(value) &&
    isText(value.request_key) &&
    UUID.test(value.request_key) &&
    isText(value.transition) &&
    isText(value.label) &&
    (value.outcome === "applied" || value.outcome === "rejected") &&
    isText(value.decision) &&
    DECISIONS.has(value.decision) &&
    isText(value.title) &&
    isText(value.body)
    ? {
        requestKey: value.request_key,
        transition: value.transition,
        label: value.label,
        outcome: value.outcome,
        decision: value.decision as ProgressDecision,
        title: value.title,
        body: value.body,
      }
    : undefined;
}

function parseHistoryItem(value: unknown): ProgressHistoryItem | null {
  return isRecord(value) &&
    isText(value.id) &&
    isText(value.kind) &&
    HISTORY_KINDS.has(value.kind) &&
    isText(value.at) &&
    isBool(value.by_viewer) &&
    isText(value.title) &&
    isOptionalText(value.detail)
    ? {
        id: value.id,
        kind: value.kind as ProgressHistoryKind,
        at: value.at,
        byViewer: value.by_viewer,
        title: value.title,
        detail: value.detail,
      }
    : null;
}

function parseRules(value: unknown): Progression["rules"] | undefined {
  if (value === null) return null;
  if (!isRecord(value) || !isText(value.bundle) || !isText(value.version)) return undefined;
  if (value.provenance !== "synthetic" && value.provenance !== "private") return undefined;
  const notice = value.notice === null ? null : parseMessage(value.notice);
  if (value.notice !== null && notice === null) return undefined;
  return { bundle: value.bundle, version: value.version, provenance: value.provenance, notice };
}

/**
 * The `progression` block; `null` when the API doesn't send one (an API older
 * than M2-03: nothing can progress), `undefined` when it is malformed.
 */
export function parseProgression(value: unknown): Progression | null | undefined {
  if (value === undefined) return null;
  if (!isRecord(value) || !isRecord(value.status) || !isText(value.status.code) || !isText(value.status.label)) return undefined;
  const gate = value.gate;
  const validGate = gate === null || (isRecord(gate) && isText(gate.code) && isText(gate.title) && isText(gate.body));
  const rules = parseRules(value.rules);
  const pathway = parseChoice(value.pathway);
  const pathwayOptions = list(value.pathway_options, parseOption);
  const stages = list(value.stages, parseStage);
  const actions = list(value.actions, parseTransition);
  const checklist = parseChecklist(value.checklist);
  const escalations = list(value.escalations, (item) =>
    isRecord(item) && isText(item.transition) && isText(item.label) && isText(item.since)
      ? { transition: item.transition, label: item.label, since: item.since }
      : null,
  );
  const history = list(value.history, parseHistoryItem);
  const attempt = parseAttempt(value.attempt);
  if (
    !validGate ||
    rules === undefined ||
    pathway === undefined ||
    pathwayOptions === null ||
    stages === null ||
    actions === null ||
    checklist === undefined ||
    escalations === null ||
    !isTexts(value.not_available) ||
    history === null ||
    attempt === undefined
  ) {
    return undefined;
  }
  const gated = gate !== null;
  return {
    status: { code: value.status.code, label: value.status.label },
    gate: isRecord(gate) ? { code: gate.code as string, title: gate.title as string, body: gate.body as string } : null,
    rules,
    pathway,
    // Under a gate on the whole Case nothing is offered, whatever the payload says.
    pathwayOptions: gated
      ? pathwayOptions.map((option) =>
          option.transition ? { ...option, transition: { ...option.transition, allowed: false, acknowledge: [] } } : option,
        )
      : pathwayOptions,
    stages,
    actions: actions
      .filter((action) => action.kind !== "pathway")
      .map((action) => (gated ? { ...action, allowed: false, acknowledge: [] } : action)),
    checklist: gated ? null : checklist,
    escalations,
    notAvailable: value.not_available,
    history,
    attempt,
  };
}

/** The checklist as a step the answers form can save (through the step answers route). */
export function checklistStep(checklist: Checklist): Step {
  return {
    key: checklist.stepKey,
    title: checklist.title,
    intro: checklist.intro,
    questions: checklist.questions.map((question) => ({
      key: question.key,
      kind: "choice",
      prompt: question.prompt,
      label: question.label,
      help: question.help,
      options: question.options,
      maxLength: null,
      allowNotSure: false,
      askWhen: null,
    })),
    available: true,
    unavailableReason: null,
    provisional: false,
    sensitive: false,
  };
}
