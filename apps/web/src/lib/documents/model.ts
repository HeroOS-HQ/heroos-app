/**
 * Document templates and safe previews (M2-04C): the shapes and strict parsers
 * for the API's three document responses (the list of templates for a Case, an
 * available template's form, and a preview). Client-safe (no server imports).
 *
 * A preview is a draft for the employer's own review, drawn by the API from a
 * private template and what the employer typed: structured text blocks, never
 * markup. The browser renders every segment as a text node, so nothing in a
 * template or a value can become HTML, a script or a link. Nothing here
 * decides availability: the API checks the Case's stage, jurisdiction and
 * holds on every request.
 *
 * `fromApi*` parse the API's snake_case JSON on the web server (null if
 * malformed); `is*` check the camelCase shapes the BFF hands to the browser.
 */

export const TEMPLATE_KEY = /^[a-z][a-z0-9_]{0,30}(\.[a-z][a-z0-9_]{0,30}){0,2}$/;
export const FIELD_KEY = TEMPLATE_KEY;
export const CHOICE_KEY = /^[a-z][a-z0-9_]{0,39}$/;
export const OPTION_VALUE = /^[a-z][a-z0-9_]{0,29}$/;

export const REASONS = [
  "rules_not_installed",
  "case_held",
  "case_not_ready",
  "not_for_jurisdiction",
  "specialist_review_required",
  "not_at_this_stage",
  "requirement_not_met",
  "requirement_unknown",
] as const;
export type Reason = (typeof REASONS)[number];

export type Notice = { title: string; body: string };
export type TemplatesInfo = {
  bundle: string;
  version: string;
  provenance: "synthetic" | "private";
  approval: "provisional" | "approved";
  /** Synthetic templates always announce themselves. */
  notice: Notice | null;
};
export type TemplateRef = { key: string; code: string; title: string; kind: string; version: number };
export type TemplateSummary = TemplateRef & { available: boolean; reason: Reason | null; reasonText: string | null };
export type DocumentsList = {
  installed: boolean;
  /** Why there's nothing to show (no templates installed). */
  unavailable: string | null;
  notice: string;
  bundle: TemplatesInfo | null;
  templates: TemplateSummary[];
};

export type SegmentKind = "text" | "value" | "missing" | "blank" | "break";
export type Segment = { kind: SegmentKind; text: string | null; field: string | null; label: string | null };
export type BlockType = "heading" | "paragraph" | "item" | "table";
export type Block = { type: BlockType; segments: Segment[]; rows: Segment[][][] };

export type FieldKind = "text" | "long_text" | "date" | "list";
export type FieldSpec = {
  key: string;
  label: string;
  kind: FieldKind;
  help: string | null;
  maxLength: number | null;
  maxItems: number | null;
  /** From this Case's own Company or subject; the employer can change or clear it. */
  suggested: string | null;
  reminder: boolean;
};
export type ChoiceSpec = {
  key: string;
  label: string;
  help: string | null;
  multiple: boolean;
  options: { value: string; label: string }[];
};
export type TemplateForm = {
  template: TemplateRef;
  bundle: TemplatesInfo;
  instructions: Block[];
  fields: FieldSpec[];
  choices: ChoiceSpec[];
  notice: string;
  reminder: string;
};
export type Watermark = { title: string; body: string; approval: string; notice: Notice | null };
export type Preview = { template: TemplateRef; watermark: Watermark; blocks: Block[]; missing: string[] };

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string";
const isOptionalText = (value: unknown): value is string | null => value === null || typeof value === "string";
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isOptionalCount = (value: unknown): value is number | null => value === null || isCount(value);

function list<T>(value: unknown, parse: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(parse);
  return items.every((item): item is T => item !== null) ? items : null;
}

const SEGMENT_KINDS = new Set<string>(["text", "value", "missing", "blank", "break"]);
const BLOCK_TYPES = new Set<string>(["heading", "paragraph", "item", "table"]);
const FIELD_KINDS = new Set<string>(["text", "long_text", "date", "list"]);

// --- shared validators (camelCase and snake_case blocks have the same keys) ----------

function parseSegment(value: unknown): Segment | null {
  if (!isRecord(value) || !isText(value.kind) || !SEGMENT_KINDS.has(value.kind)) return null;
  const text = value.text ?? null;
  const field = value.field ?? null;
  const label = value.label ?? null;
  if (!isOptionalText(text) || !isOptionalText(field) || !isOptionalText(label)) return null;
  const kind = value.kind as SegmentKind;
  // Each kind carries exactly what it shows.
  if ((kind === "text" || kind === "value") && text === null) return null;
  if ((kind === "missing" || kind === "blank") && label === null) return null;
  return { kind, text, field, label };
}

function parseBlock(value: unknown): Block | null {
  if (!isRecord(value) || !isText(value.type) || !BLOCK_TYPES.has(value.type)) return null;
  const segments = list(value.segments ?? [], parseSegment);
  const rows = list(value.rows ?? [], (row) => list(row, (cell) => list(cell, parseSegment)));
  if (segments === null || rows === null) return null;
  return { type: value.type as BlockType, segments, rows };
}

function parseNotice(value: unknown): Notice | null | undefined {
  if (value === null) return null;
  return isRecord(value) && isText(value.title) && isText(value.body) ? { title: value.title, body: value.body } : undefined;
}

function parseRef(value: unknown): TemplateRef | null {
  return isRecord(value) &&
    isText(value.key) &&
    TEMPLATE_KEY.test(value.key) &&
    isText(value.code) &&
    isText(value.title) &&
    isText(value.kind) &&
    isCount(value.version) &&
    value.version >= 1
    ? { key: value.key, code: value.code, title: value.title, kind: value.kind, version: value.version }
    : null;
}

function parseInfo(value: unknown): TemplatesInfo | null {
  if (!isRecord(value)) return null;
  const notice = parseNotice(value.notice);
  if (
    !isText(value.bundle) ||
    !isText(value.version) ||
    !(value.provenance === "synthetic" || value.provenance === "private") ||
    !(value.approval === "provisional" || value.approval === "approved") ||
    notice === undefined ||
    // Synthetic templates are never shown without their notice.
    (value.provenance === "synthetic" && notice === null)
  ) {
    return null;
  }
  return { bundle: value.bundle, version: value.version, provenance: value.provenance, approval: value.approval, notice };
}

// --- the API's JSON (web server) -------------------------------------------------------

export function fromApiDocumentsList(value: unknown): DocumentsList | null {
  if (!isRecord(value) || typeof value.installed !== "boolean" || !isOptionalText(value.unavailable) || !isText(value.notice)) {
    return null;
  }
  const bundle = value.bundle === null ? null : parseInfo(value.bundle);
  const templates = list(value.templates, (item): TemplateSummary | null => {
    const ref = parseRef(item);
    if (ref === null || !isRecord(item) || typeof item.available !== "boolean" || !isOptionalText(item.reason_text)) return null;
    const reason = item.reason;
    if (!(reason === null || (isText(reason) && (REASONS as readonly string[]).includes(reason)))) return null;
    // Available exactly when there is no reason, whatever the payload says.
    if (item.available !== (reason === null)) return null;
    return { ...ref, available: item.available, reason: reason as Reason | null, reasonText: item.reason_text };
  });
  if ((value.bundle !== null && bundle === null) || templates === null) return null;
  if (value.installed !== (bundle !== null)) return null;
  return { installed: value.installed, unavailable: value.unavailable, notice: value.notice, bundle, templates };
}

function fromApiField(value: unknown): FieldSpec | null {
  if (
    !isRecord(value) ||
    !isText(value.key) ||
    !FIELD_KEY.test(value.key) ||
    !isText(value.label) ||
    !isText(value.kind) ||
    !FIELD_KINDS.has(value.kind) ||
    !isOptionalText(value.help) ||
    !isOptionalCount(value.max_length) ||
    !isOptionalCount(value.max_items) ||
    !isOptionalText(value.suggested) ||
    typeof value.reminder !== "boolean"
  ) {
    return null;
  }
  const kind = value.kind as FieldKind;
  if (kind !== "date" && value.max_length === null) return null;
  if ((kind === "list") !== (value.max_items !== null)) return null;
  return {
    key: value.key,
    label: value.label,
    kind,
    help: value.help,
    maxLength: value.max_length,
    maxItems: value.max_items,
    suggested: value.suggested,
    reminder: value.reminder,
  };
}

function fromApiChoice(value: unknown): ChoiceSpec | null {
  if (
    !isRecord(value) ||
    !isText(value.key) ||
    !CHOICE_KEY.test(value.key) ||
    !isText(value.label) ||
    !isOptionalText(value.help) ||
    typeof value.multiple !== "boolean"
  ) {
    return null;
  }
  const options = list(value.options, (option) =>
    isRecord(option) && isText(option.value) && OPTION_VALUE.test(option.value) && isText(option.label)
      ? { value: option.value, label: option.label }
      : null,
  );
  if (options === null || options.length < 2) return null;
  return { key: value.key, label: value.label, help: value.help, multiple: value.multiple, options };
}

export function fromApiTemplateForm(value: unknown): TemplateForm | null {
  if (!isRecord(value) || !isText(value.notice) || !isText(value.reminder)) return null;
  const template = parseRef(value.template);
  const bundle = parseInfo(value.bundle);
  const instructions = list(value.instructions, parseBlock);
  const fields = list(value.fields, fromApiField);
  const choices = list(value.choices, fromApiChoice);
  if (template === null || bundle === null || instructions === null || fields === null || choices === null) return null;
  return { template, bundle, instructions, fields, choices, notice: value.notice, reminder: value.reminder };
}

export function fromApiPreview(value: unknown): Preview | null {
  if (!isRecord(value) || !isRecord(value.watermark)) return null;
  const template = parseRef(value.template);
  const blocks = list(value.blocks, parseBlock);
  const watermark = value.watermark;
  const notice = parseNotice(watermark.notice);
  const missing = list(value.missing, (item) => (isText(item) ? item : null));
  if (
    template === null ||
    blocks === null ||
    missing === null ||
    notice === undefined ||
    !isText(watermark.title) ||
    watermark.title === "" ||
    !isText(watermark.body) ||
    !isText(watermark.approval)
  ) {
    return null;
  }
  return {
    template,
    watermark: { title: watermark.title, body: watermark.body, approval: watermark.approval, notice },
    blocks,
    missing,
  };
}

// --- the BFF's JSON (browser) ----------------------------------------------------------

/** A templates list as the BFF returns it (shape only; the server parsed it). */
export function isDocumentsList(value: unknown): value is DocumentsList {
  return (
    isRecord(value) &&
    typeof value.installed === "boolean" &&
    isOptionalText(value.unavailable) &&
    isText(value.notice) &&
    Array.isArray(value.templates) &&
    value.templates.every(
      (item) =>
        isRecord(item) &&
        isText(item.key) &&
        isText(item.code) &&
        isText(item.title) &&
        typeof item.available === "boolean" &&
        isOptionalText(item.reasonText),
    )
  );
}

/** A template form as the BFF returns it. */
export function isTemplateForm(value: unknown): value is TemplateForm {
  return (
    isRecord(value) &&
    parseRef(value.template) !== null &&
    isRecord(value.bundle) &&
    list(value.instructions, parseBlock) !== null &&
    Array.isArray(value.fields) &&
    value.fields.every((field) => isRecord(field) && isText(field.key) && isText(field.label) && FIELD_KINDS.has(String(field.kind))) &&
    Array.isArray(value.choices) &&
    isText(value.notice) &&
    isText(value.reminder)
  );
}

/** A preview as the BFF returns it: every block and segment re-checked before rendering. */
export function isPreview(value: unknown): value is Preview {
  return (
    isRecord(value) &&
    parseRef(value.template) !== null &&
    isRecord(value.watermark) &&
    isText(value.watermark.title) &&
    value.watermark.title !== "" &&
    isText(value.watermark.body) &&
    list(value.blocks, parseBlock) !== null &&
    Array.isArray(value.missing)
  );
}

// --- copy ------------------------------------------------------------------------------

export const KIND_LABEL: Record<string, string> = { letter: "Letter", email: "Email", minutes: "Meeting record" };
