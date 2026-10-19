// @vitest-environment node
import { describe, expect, it } from "vitest";

import { apiDocuments, apiForm, apiInfo, apiNotInstalled, apiPreview, apiSummary, HOSTILE, NAME } from "@/test/document-fixtures";

import { checkDraft, initialValues, previewBody, toggleChoice } from "./draft";
import { fromApiDocumentsList, fromApiPreview, fromApiTemplateForm, isDocumentsList, isPreview, isTemplateForm } from "./model";
import { parsePreviewRequest } from "./requests";

const form = () => fromApiTemplateForm(apiForm())!;

describe("document parsers (M2-04C)", () => {
  it("parses the API's list, form and preview into camelCase shapes", () => {
    const list = fromApiDocumentsList(apiDocuments())!;
    expect(list.templates[0]).toMatchObject({ code: "TEST-01", available: true, reason: null, reasonText: null });
    expect(list.bundle).toMatchObject({ provenance: "synthetic", approval: "provisional" });
    expect(isDocumentsList(list)).toBe(true);
    expect(form().fields.map((field) => [field.key, field.kind, field.maxItems])).toEqual([
      ["document_date", "date", null],
      ["recipient_name", "text", null],
      ["discussion_points", "list", 3],
      ["summary", "long_text", null],
    ]);
    expect(isTemplateForm(form())).toBe(true);
    const preview = fromApiPreview(apiPreview())!;
    expect(preview.watermark.title).toBe("Preview — not issued");
    expect(isPreview(preview)).toBe(true);
    expect(fromApiDocumentsList(apiNotInstalled())).toMatchObject({ installed: false, templates: [] });
  });

  it.each([
    ["a template marked available with a reason", apiDocuments([apiSummary({ reason: "case_held", reason_text: "x" })])],
    ["an unknown reason", apiDocuments([apiSummary({ available: false, reason: "approved_by_magic", reason_text: "x" })])],
    ["a malformed template key", apiDocuments([apiSummary({ key: "../workflow" })])],
    ["synthetic templates without their notice", apiDocuments(undefined, { bundle: apiInfo({ notice: null }) })],
    ["an unknown approval", apiDocuments(undefined, { bundle: apiInfo({ approval: "legal" }) })],
    ["installed without a bundle", apiDocuments(undefined, { bundle: null })],
  ])("refuses a list with %s", (_, body) => {
    expect(fromApiDocumentsList(body)).toBeNull();
  });

  it.each([
    ["an unknown segment kind", apiPreview(undefined, { blocks: [{ type: "paragraph", segments: [{ kind: "html", text: "<b>x</b>" }], rows: [] }] })],
    ["a value without text", apiPreview(undefined, { blocks: [{ type: "paragraph", segments: [{ kind: "value", text: null }], rows: [] }] })],
    ["a gap without a label", apiPreview(undefined, { blocks: [{ type: "paragraph", segments: [{ kind: "missing", field: "x" }], rows: [] }] })],
    ["an unknown block type", apiPreview(undefined, { blocks: [{ type: "iframe", segments: [], rows: [] }] })],
    ["no watermark title", apiPreview(undefined, { watermark: { title: "", body: "x", approval: "x", notice: null } })],
  ])("refuses a preview with %s", (_, body) => {
    expect(fromApiPreview(body)).toBeNull();
  });

  it("refuses a form whose fields don't fit their kind", () => {
    const fields = apiForm().fields;
    expect(fromApiTemplateForm(apiForm({ fields: [{ ...fields[1], max_length: null }] }))).toBeNull();
    expect(fromApiTemplateForm(apiForm({ fields: [{ ...fields[2], max_items: null }] }))).toBeNull();
    expect(fromApiTemplateForm(apiForm({ fields: [{ ...fields[1], kind: "html" }] }))).toBeNull();
    expect(fromApiTemplateForm(apiForm({ choices: [{ ...apiForm().choices[0], options: [{ value: "x", label: "X" }] }] }))).toBeNull();
  });

  it("keeps hostile values as plain strings (rendering decides nothing)", () => {
    const preview = fromApiPreview(apiPreview(HOSTILE))!;
    expect(preview.blocks[1].segments.slice(1).map((segment) => segment.text)).toEqual(HOSTILE);
  });
});

describe("the form draft", () => {
  it("starts from the case's suggestions and leaves everything else empty", () => {
    expect(initialValues(form())).toEqual({ document_date: "", recipient_name: NAME, discussion_points: [""], summary: "" });
  });

  it("checks what the API checks, and leaves empty fields to show as gaps", () => {
    const f = form();
    expect(checkDraft(f, initialValues(f))).toEqual({});
    expect(
      checkDraft(f, {
        document_date: "2026-02-30",
        recipient_name: "Right‮to-left",
        discussion_points: ["a", "b", "c", "d"],
        summary: "Line one\nLine two\twith a tab",
      }),
    ).toEqual({
      document_date: "Enter a real date.",
      recipient_name: "Remove the invisible or special characters (they can come from copying and pasting).",
      discussion_points: "List at most 3 entries.",
    });
    expect(checkDraft(f, { document_date: "1989-12-31", recipient_name: "x".repeat(121), summary: "Zero​width" })).toEqual({
      document_date: "Check the year: it must be between 1990 and 2100.",
      recipient_name: "Keep it to 120 characters or fewer.",
      summary: "Remove the invisible or special characters (they can come from copying and pasting).",
    });
    // A non-breaking space is refused, like by the API; an ordinary one isn't.
    expect(checkDraft(f, { recipient_name: "Sam Example" })).toHaveProperty("recipient_name");
    expect(checkDraft(f, { recipient_name: "Sam Example" })).toEqual({});
  });

  it("sends filled fields trimmed, drops empty ones and keeps one option of a single choice", () => {
    const f = form();
    const body = previewBody(
      f,
      { document_date: "", recipient_name: `  ${NAME}  `, discussion_points: [" first ", "", "second"], summary: "   " },
      { meeting_format: ["online", "in_person"], unknown_choice: ["x"] },
    );
    expect(body).toEqual({
      templateVersion: 1,
      values: { recipient_name: NAME, discussion_points: ["first", "second"] },
      choices: { meeting_format: ["online"] },
    });
    const choice = f.choices[0];
    expect(toggleChoice(choice, ["in_person"], "online")).toEqual(["online"]);
    expect(toggleChoice({ ...choice, multiple: true }, ["in_person"], "online")).toEqual(["in_person", "online"]);
    expect(toggleChoice({ ...choice, multiple: true }, ["in_person", "online"], "online")).toEqual(["in_person"]);
  });
});

describe("parsePreviewRequest (BFF rebuild)", () => {
  const valid = { templateVersion: 1, values: { recipient_name: NAME, points: ["a", "b"] }, choices: { meeting_format: ["online"] } };

  it("rebuilds a valid request into the API's shape", () => {
    expect(parsePreviewRequest(valid)).toEqual({
      ok: true,
      value: { template_version: 1, values: { recipient_name: NAME, points: ["a", "b"] }, choices: { meeting_format: ["online"] } },
    });
  });

  it.each([
    ["an unknown top-level key", { ...valid, requestKey: "x" }],
    ["a missing version", { values: {}, choices: {} }],
    ["a version that isn't a positive integer", { ...valid, templateVersion: 0 }],
    ["a malformed field key", { ...valid, values: { "<script>": "x" } }],
    ["a prototype key", { ...valid, values: JSON.parse('{"__proto__": "x"}') as Record<string, string> }],
    ["a value that isn't text", { ...valid, values: { recipient_name: 7 } }],
    ["an oversized value", { ...valid, values: { summary: "x".repeat(4001) } }],
    ["too many list entries", { ...valid, values: { points: Array(31).fill("x") } }],
    ["too many fields", { ...valid, values: Object.fromEntries(Array.from({ length: 61 }, (_, i) => [`f${i}`, "x"])) }],
    ["a malformed option", { ...valid, choices: { meeting_format: ["Online!"] } }],
    ["a choice that isn't a list", { ...valid, choices: { meeting_format: "online" } }],
  ])("refuses %s", (_, body) => {
    expect(parsePreviewRequest(body)).toEqual({ ok: false });
  });
});
