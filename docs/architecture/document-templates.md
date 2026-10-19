# Document Templates and Safe Previews (M2-04C, first slice)

**Status:** Implemented (M2-04C phases C1–C2), not deployed. No migration:
contract stays 7.\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform ("Generate documents from approved templates")\
**Related:** [Workflow Progression](workflow-progression.md) (M2-03, the rule
bundle this mirrors), [Employer Decisions and Unified Case History](workflow-decisions.md)
(M2-04), [Private Object Storage](private-object-storage.md),
[Privacy Decision Register](../privacy/decision-register.md) (PRIV-004)

## 1. What this slice is

A Company administrator, on a Disciplinary Case, under a new **Documents**
section:

1. sees which letter and email templates can be previewed **at the Case's
   current stage**, and for every other template, why not;
2. opens an available template: its fields, its choices between alternative
   paragraphs, and the employer instructions that come with it (shown beside
   the form, never in the document);
3. fills it in and sees a **preview**: the template's wording with the typed
   details, as structured text, watermarked "Preview — not issued" at the top,
   at the bottom and on every printed page, with a visible gap for anything
   not given.

### What it is not

- It doesn't **issue, send, sign, deliver, download or store** a document,
  and doesn't record an acknowledgment or a refusal. There is no route,
  button or table for any of it. That is later work (§9).
- **Nothing is kept.** A preview exists only in one request and its response.
  No value is written to the database, logged, cached or remembered by the
  browser (§5).
- **No AI** and no inference: a field is filled only with what the employer
  typed, or with a suggestion taken from the Case's own Company or subject that
  the employer can change or clear.
- A preview **never changes the Case**: no stage moves, no hold is released,
  nothing is recorded. An employer decision record (M2-04) never makes a
  template available.
- **No template wording is in this repository** (it is public). JJ's templates
  reach the API as a private, pinned bundle; only fictional synthetic
  templates are tracked, for tests.

## 2. The template bundle (`app/documents/bundle.py`)

The templates are proprietary content, so the engine is generic and the
content is data, exactly like the rule bundle (M2-03):

- **Configured** by `HEROOS_TEMPLATE_BUNDLE_PATH` (an absolute path in
  server-side storage only the API can read) and
  `HEROOS_TEMPLATE_BUNDLE_SHA256` (the pin). Set both or neither, and never
  without a rule bundle. Unset: the Documents section says templates aren't
  available in this environment; everything else works.
- **Read once at startup**, never re-read while running. The file's SHA-256
  must equal the pin; the JSON must match schema `heroos.template-bundle/1`
  exactly; the bundle must name the installed rule bundle (id and version),
  and every stage and checklist answer it refers to must exist there. Any
  failure **stops startup** with a fixed code and a structural location,
  never wording. Nothing falls back.
- **Production** refuses a synthetic bundle and any bundle whose wording is
  still `provisional`.
- **Stable keys, display codes as data.** A template is identified by a key
  such as `disc.example.letter`; its display code (`EX-01`) is a label in
  the bundle, so renumbering a template is a content edit, not a code change.

### Schema

```
{schema, bundle, version, provenance: synthetic|private, approval: provisional|approved,
 workflow, rule_bundle: {bundle, versions}, notice: {title, body} | null,
 fields: [{key, label, kind: text|long_text|date|list, max?, items?, help?,
           suggest?: company_name|subject_name, reminder?}],
 templates: [{key, code, title, kind: letter|email|minutes, version,
   source_sha256 (private: the approved source document's SHA-256), review: employer|specialist_first,
   jurisdictions: {<code>: {stages: [stage], require?: predicate}},
   instructions: [block], choices: [{key, label, help?, multiple, options}], body: [block]}]}

block   = {type: heading|paragraph|item, content: [segment], when?: {choice, in}, repeat?: <list field>}
        | {type: table, rows: [[[segment]]], when?}
segment = {text} | {field} | {blank: label} | {break: true}
```

Every field and choice a template uses must exist and be used; a list field is
written item by item in its own `repeat` blocks; preconditions use the M2-03
predicate language and may read intake answers and stage checklist answers,
**never a sensitive screening answer**. Bounds (1 MiB, 32 templates, 400 blocks,
60 fields per template, 30 list entries, 4,000 characters per value) are input
limits, not product rules.

`review: specialist_first` marks a template that needs a person's specialist
review before it may be offered. No such review exists in HeroOS yet, so those
templates are never available (JJ decides which templates need it).

## 3. Availability (`app/documents/eligibility.py`)

Checked **server-side on every request**, from the progression evaluation and
the Case's answers only; the first reason that applies is given:

| # | Reason | When |
| --- | --- | --- |
| 1 | `rules_not_installed` | No rule bundle installed |
| 2 | `case_held` | Held for specialist review, or any escalation recorded |
| 3 | `case_not_ready` | Anything else that stops the Case moving on: jurisdiction not confirmed, intake not recorded (a disabled or uncertain screening never counts as cleared), jurisdiction not covered, rules version changed, workflow closed |
| 4 | `not_for_jurisdiction` | The template isn't offered in the Case's jurisdiction |
| 5 | `specialist_review_required` | The template needs a specialist's review first |
| 6 | `not_at_this_stage` | The stage in progress isn't one the template is bound to |
| 7 | `requirement_not_met` / `requirement_unknown` | Its precondition is false, or unknown (unanswered or "Not sure" never counts) |

The function's inputs can't include an employer decision record; an import
boundary test keeps `app/documents` and `app/api/documents.py` away from
decision records, and keeps the engine free of any database access.

## 4. API (`app/api/documents.py`)

Company administrators only, like every Disciplinary route, in a transaction
that **cannot write** (`CompanyAdminReadOnlyDb`: PostgreSQL's
`SET TRANSACTION READ ONLY`, and an ORM guard refusing any flush).

| Route | Answer |
| --- | --- |
| `GET .../cases/{case}/documents` | Every template and whether it can be previewed now, with the reason and a plain-language explanation; the bundle's provenance, approval and (synthetic) notice |
| `GET .../cases/{case}/documents/{template}` | An available template's form: fields (with suggestions from this Case's Company or subject), choices, instructions, the privacy notice and the reminder about personal details. 409 if not available now |
| `POST .../cases/{case}/documents/{template}/preview` | Body `{template_version, values, choices}`. The filled template as blocks of typed segments (`text`, `value`, `missing`, `blank`, `break`) and the watermark. POST so personal details never travel in a URL. 409 if not available now or the version changed; 422 names fields only, never values |

Values are validated like M2-04 text (no control, bidi or zero-width
characters; bounded); dates are written out ("18 October 2026"). There is no
template language: a value is inserted verbatim as a text segment, so nothing
typed can change the template, run anything or become markup or a link.

## 5. Privacy and security

| Concern | Control | Evidence |
| --- | --- | --- |
| Previewed details kept | No table; read-only transaction; nothing logged but the template key and how many gaps remain; `Cache-Control: no-store` on every API and BFF response; the browser keeps the draft in memory only, with autofill off | API tests (row counts, logs), PostgreSQL tests (`SHOW transaction_read_only` = on for every document request; no row anywhere contains a previewed value), e2e DOCS-4/5/13 |
| XSS or injection through a value or template | Structured segments, rendered by React as text nodes; no HTML string anywhere (`dangerouslySetInnerHTML`, `innerHTML` and `eval` are refused by a source test); no CSP change | API, web and e2e tests with markup, `javascript:` links and template syntax (DOCS-3) |
| Template wording leaving the server | Fetched at run time for one Case by an administrator; never in the web build (source and built-asset scans); never in logs, errors or the validation tool's output | Web boundary test, e2e DOCS-13/14, configuration tests |
| Tampered or mismatched templates | SHA-256 pin, strict schema, cross-check with the rule bundle, startup refusal | Unit and configuration tests, e2e DOCS-12 |
| A preview mistaken for an issued letter | Watermark top, bottom and on every printed page; provisional wording labelled; no download, send, print or copy action in the code | Component and e2e tests. **Limit:** text on screen can always be copied by hand; the watermark and the notices say what it is |
| Access | Administrators only (members 403); another Company's Case 404; RLS underneath | API, PostgreSQL and e2e tests |

## 6. Web

- **Documents** section in the case workspace (administrators only), after
  "Decisions & history". It reads the list when the Case loads and again
  whenever the Case's revision changes (a transition, a checklist answer).
- BFF routes: `GET /bff/.../documents`, `GET /bff/.../documents/{template}`
  (same-origin and a session; no query) and `POST /bff/.../documents/{template}/preview`
  (the shared CSRF, content-type and session guard; 32 KiB, a whole letter's
  details; the body rebuilt field by field).
- An older API without document routes answers 404: the section says
  documents aren't available yet.

## 7. Operating it

- **Validate** a bundle before deployment (prints the pin, counts per
  template and review mode, never wording):
  `uv run python -m scripts.template_bundle validate TEMPLATES RULES [--production]`.
- **Install** (separately authorized): place the file next to the rule bundle,
  set both variables, restart the API. A refusal stops startup; remove both
  variables to run without templates.
- **Git** ignores `*.private-templates.json`, `*.private-mapping.json`,
  `private-template-bundles/`, `template-review-packs/` and Word documents, as
  a second guard; a test fails if any template bundle other than the
  synthetic one, or any Word document, is tracked.

## 8. Tests

- API: `tests/documents/test_templates.py` (schema, loader, cross-check,
  values, rendering, eligibility), `tests/auth/test_documents_api.py` (routes,
  availability, validation, access, nothing written or logged),
  `tests/test_template_bundle_configuration.py` (settings, startup, repository
  hygiene, the validation tool), `tests/tenant_isolation/test_workflow_documents.py`
  (PostgreSQL: read-only transactions, no trace, isolation),
  `tests/test_import_boundaries.py` (routes, read-only scope, no decision records).
- Web: `lib/documents/documents.test.ts`, `lib/server/documents-bff.test.ts`,
  `components/cases/documents.test.tsx`, `security-boundaries.test.ts`.
- End to end: the `documents` suite (DOCS-0 to DOCS-15).

## 9. Not in this slice

- Converting JJ's Word documents into a template bundle (the offline
  converter, phase C3) and installing any real template (C4/C5, after JJ's
  content decisions, legal approval and a separate release authorization).
- Saving drafts, issuing, delivering, acknowledging, DOCX/PDF output and
  storage (ADR-005): blocked on PRIV-004 (document retention) and JJ's
  lifecycle decisions.
- Previews appearing in the case history (nothing is stored to show).
