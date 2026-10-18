/**
 * API-shaped (snake_case) document responses for tests (M2-04C). Fictional,
 * synthetic content only: these are not HeroOS or JJ templates.
 */

export const TEMPLATE_KEY = "synthetic.check_in_note";
export const NAME = "[SYNTHETIC] Sam Example";
// Values that must stay literal text in a preview.
export const HOSTILE = [
  "<script>alert(1)</script>",
  "<img src=x onerror=alert(1)>",
  "javascript:alert(1)",
  "https://example.invalid/phish",
  "{{7*7}} ${7*7}",
];

export const apiNotice = { title: "Synthetic test templates", body: "Fictional test templates." };
export const apiInfo = (overrides: Record<string, unknown> = {}) => ({
  bundle: "synthetic-templates",
  version: "synthetic.1",
  provenance: "synthetic",
  approval: "provisional",
  notice: apiNotice,
  ...overrides,
});

const ref = (overrides: Record<string, unknown> = {}) => ({
  key: TEMPLATE_KEY,
  code: "TEST-01",
  title: "Synthetic test letter: check-in note",
  kind: "letter",
  version: 1,
  ...overrides,
});

export const apiSummary = (overrides: Record<string, unknown> = {}) => ({
  ...ref(),
  available: true,
  reason: null,
  reason_text: null,
  ...overrides,
});

export const apiDocuments = (templates: unknown[] = [apiSummary()], overrides: Record<string, unknown> = {}) => ({
  installed: true,
  unavailable: null,
  notice: "A preview is a draft for your own review. Nothing you type here is saved, sent or kept.",
  bundle: apiInfo(),
  templates,
  ...overrides,
});

export const apiNotInstalled = () => ({
  installed: false,
  unavailable: "Document templates aren't available in this environment.",
  notice: "A preview is a draft for your own review.",
  bundle: null,
  templates: [],
});

export const unavailableSummary = (reason: string, text: string, overrides: Record<string, unknown> = {}) =>
  apiSummary({
    key: "synthetic.written_note",
    code: "TEST-02",
    title: "Synthetic test letter: written note",
    available: false,
    reason,
    reason_text: text,
    ...overrides,
  });

const text = (value: string) => ({ kind: "text", text: value, field: null, label: null });

export const apiForm = (overrides: Record<string, unknown> = {}) => ({
  template: ref(),
  bundle: apiInfo(),
  instructions: [{ type: "paragraph", segments: [text("[SYNTHETIC] Fill in the fields.")], rows: [] }],
  fields: [
    { key: "document_date", label: "Date of the letter", kind: "date", help: null, max_length: null, max_items: null, suggested: null, reminder: false },
    { key: "recipient_name", label: "Recipient's name", kind: "text", help: null, max_length: 120, max_items: null, suggested: NAME, reminder: false },
    { key: "discussion_points", label: "Points discussed", kind: "list", help: "One point per entry.", max_length: 200, max_items: 3, suggested: null, reminder: true },
    { key: "summary", label: "Short summary", kind: "long_text", help: null, max_length: 2000, max_items: null, suggested: null, reminder: true },
  ],
  choices: [
    {
      key: "meeting_format",
      label: "How the test conversation took place",
      help: null,
      multiple: false,
      options: [
        { value: "in_person", label: "In person" },
        { value: "online", label: "Online" },
      ],
    },
  ],
  notice: "A preview is a draft for your own review. Nothing you type here is saved, sent or kept.",
  reminder: "Keep to the facts. Leave out health, family, religion or other personal details.",
  ...overrides,
});

export const apiPreview = (values: string[] = [NAME], overrides: Record<string, unknown> = {}) => ({
  template: ref(),
  watermark: {
    title: "Preview — not issued",
    body: "Draft for the employer's review only. HeroOS doesn't give legal advice.",
    approval: "Template wording: provisional, not approved for use.",
    notice: apiNotice,
  },
  blocks: [
    { type: "heading", segments: [text("[SYNTHETIC] Test letter, not for real use")], rows: [] },
    {
      type: "paragraph",
      segments: [text("To: "), ...values.map((value) => ({ kind: "value", text: value, field: "recipient_name", label: null }))],
      rows: [],
    },
    { type: "paragraph", segments: [{ kind: "missing", text: null, field: "summary", label: "Short summary" }], rows: [] },
    { type: "item", segments: [{ kind: "value", text: "[SYNTHETIC] Arrival times", field: "discussion_points", label: null }], rows: [] },
    {
      type: "table",
      segments: [],
      rows: [[[text("Signed")], [{ kind: "blank", text: null, field: null, label: "Signature" }]]],
    },
  ],
  missing: ["summary"],
  ...overrides,
});
