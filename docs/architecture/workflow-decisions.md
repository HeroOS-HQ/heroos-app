# Employer Decisions and Unified Case History (M2-04, first slice)

**Status:** Implemented (M2-04 first slice), not deployed. Migration D4,
contract 7.\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform ("Preserve decisions and case history")\
**Related:** [Workflow Case Foundation](workflow-foundation.md) (M2-01),
[Disciplinary Intake](disciplinary-intake.md) (M2-02),
[Workflow Progression](workflow-progression.md) (M2-03),
[Tenant Isolation](tenant-isolation.md), [Privacy Decision Register](../privacy/decision-register.md)

## 1. What M2-04 is

A Company administrator, in the existing Disciplinary workspace, under a new
**Decisions & history** section:

1. records a factual employer decision or observation: what it is (a safe
   category), a one-line summary, the date it happened, who the employer says
   is responsible, an explanation, and whether supporting evidence exists (with
   references to it);
2. sees it at once in the Case's **unified history**, next to everything else
   that happened to the Case;
3. corrects it, or adds a clarification, as a new version: the earlier version
   stays in the history, marked as replaced;
4. finds the records, every version and the history again after a reload or a
   new sign-in;
5. sees the holds and limits that still apply, and that a record changes none
   of them.

It works with or without an installed rule bundle.

## 2. A record is not an authorization

| | Employer record (M2-04) | Workflow authorization (M2-03) |
| --- | --- | --- |
| What it is | The employer's own account of what it did or decided | A backend decision that a stage transition is permitted now |
| Who decides | The employer; HeroOS stores it as entered and verifies nothing | The engine, from the installed (approved) rules |
| Effect on the Case | None: no stage moves, no hold is released, nothing counts as a warning or an outcome | The Case's position changes, or the refusal is recorded |

The separation is structural, not only in wording:

- **No authorizing vocabulary exists.** The categories are factual only
  (§3.1). A warning, suspension, financial penalty, dismissal, finding of
  serious misconduct or specialist approval isn't a category: the API refuses
  it (422) and the database refuses it (CHECK constraint).
- **The write path never reaches the engine.** Recording takes the instance
  lock and the revision like every write, reads the workflow context to store
  it, and writes one row. It never evaluates or records a transition, never
  writes a progress event, evaluation, answer or fact, and the request has no
  field that could carry an approval, a status, a stage or an actor.
- **Tests prove it** at every level: a record on a held Case leaves it held and
  a pathway still escalates; a record saying "stage complete, formal warning
  issued" leaves the stage in progress and its completion refused; nothing else
  is written (API, PostgreSQL and end-to-end suites).

The screen says the same in plain words: the section's notice, the "Holds and
limits" box, the form's footer and the confirmation after a save.

## 3. Decision records

`app/workflows/decisions.py` (vocabulary, validation, chains) and
`app/api/decisions.py` (request and response models).

### 3.1 Categories

| Key | Label |
| --- | --- |
| `internal_review_completed` | Internal review completed |
| `information_requested` | Additional information requested |
| `meeting_recorded` | Meeting or discussion recorded |
| `employer_observation` | Employer observation |
| `internal_pause_or_follow_up` | Internal pause or follow-up decision |
| `other_note` | Other factual case note |

Listed by `GET /companies/{id}/workflows/{key}/decision-categories` and in the
Case view. The web app only ever offers the categories it knows, whatever a
payload says.

### 3.2 Attribution

- **The authenticated actor** (`recorded_by_user_id`) is the signed-in
  administrator, taken from the session. The request has no actor field
  (`extra="forbid"`: any extra field is a 422).
- **The responsible decision-maker** is the employer's statement: `recorder`
  (the administrator recording it) or `other`, with a role or job title
  (`decision_maker_role`, at most 120 characters; a name isn't needed). It is
  stored and shown as "as stated by your company", never as a verified identity
  and never instead of the actor. It can't name HeroOS ("HeroOS specialist",
  including full-width look-alikes): HeroOS makes no decision.

### 3.3 Evidence references

The employer says whether supporting evidence exists: `held` (at least one
reference), `none` (explicitly unavailable) or `not_sure`. Each reference has a
kind (internal document, meeting note, company policy, other), a description
(at most 300 characters) and an optional location such as a reference number
(at most 200), at most 10 references. HeroOS stores **references only**: no
file is uploaded, no link is accepted (anything with `://`, a `www.` address,
or a URI with a known scheme such as `javascript:`, `data:`, `file:` or
`mailto:`; checked on the NFKC form, so full-width look-alikes count), nothing
is fetched or parsed, and the screen says HeroOS doesn't check evidence. A
reference can't present itself as a HeroOS document (it can't name HeroOS).
Internal locations such as a share path or a folder name are references, not
links: they are stored and shown as text only. Everything is rendered as text
(React escapes it; nothing becomes a link or HTML).

### 3.4 Validation

Text is validated, never normalized (the web app trims before sending): summary
1–200 characters on one line, explanation 1–4,000 characters (line breaks and
tabs allowed), change reason 1–500, no control or invisible formatting
characters (bidi overrides, zero-width characters, line separators). The API
counts code points; the browser and the BFF count UTF-16 units, so they are
never more permissive than the API. The date is exactly
`YYYY-MM-DD`, not before 1990 and not after tomorrow (UTC, for time zones ahead
of it). Errors name the field only and never echo a value.

### 3.5 Corrections and clarifications

Nothing is updated in place. `POST …/decisions/{record}/corrections` with
`relation` = `correction` (the earlier version was wrong) or `clarification`
(it was incomplete) and a `change_reason` writes a **new complete version**
that supersedes the record:

- every version of a record shares a `chain_id` (the first version's id); the
  latest version is **current**, every earlier one is **superseded** and stays
  readable, with its own date, actor and content;
- only the current version can be superseded (409 otherwise), so a chain is a
  single line;
- a correction can only target a record of the **same chain, Case and
  Company**: the composite foreign key `(company_id, instance_id, chain_id,
  supersedes_id)` → `(company_id, instance_id, chain_id, id)` refuses anything
  else, and the API answers 404 for another Case's or Company's record (the
  same answer as a random id);
- **no cycle can exist**: a new row can only point at an existing row, rows are
  never updated, a first version can never become a correction (shape CHECK:
  `chain_id = id` exactly when `supersedes_id IS NULL`), and `supersedes_id` is
  unique (one successor per version).

## 4. The unified case history

`app/workflows/timeline.py`: one projection, composed on read from the
append-only records the earlier slices already keep, with the wording they
already use. **No second event store.**

| Source | Entries |
| --- | --- |
| M2-01 Case and answers | Case created; answers saved (labels only, counts for sensitive questions) |
| M2-02 intake evaluations | Jurisdiction confirmed, holds placed/kept/lifted, screening result, cautions, intake recorded |
| M2-03 progress events | Pathway recorded, stage started/completed, request not allowed, specialist review needed |
| M2-04 decision records | Employer record, corrected, clarified (the summary only; the explanation stays with the record) |

Every entry has a stable id, a timestamp, a category, a kind, a **nature**, a
short neutral title and detail, the actor where there is one (the viewer or
another administrator), the source record (type and id), a safe status and, for
decision records, the correction links:

| Nature | Shown as | Meaning |
| --- | --- | --- |
| `employer_record` | Employer record | Entered by the employer (answers, decision records); not verified by HeroOS |
| `system_check` | HeroOS check | An outcome of HeroOS's fixed checks |
| `refused_request` | Not allowed: nothing changed | A request the rules refused; the Case didn't move |
| `workflow_change` | Workflow step | A change actually recorded in the workflow |

**Order** is causal and total: by instance revision (every write that changes a
Case produces one, under the instance lock), then within a revision what
produced it, what its evaluation changed, refusals, escalations, then time,
then the sources' own order. Timestamps alone can disagree with the commit order
(a transaction's `now()` is its start), and many entries share one; the order
never depends on the clock alone. **Paging**: newest first, `limit` 1–100
(default 50), `before` = the id of the last entry seen; entries never change or
disappear, so a cursor stays valid while new entries arrive (they go on top).
One rare exception: two requests refused at the same revision are ordered by
their transaction's start time, so if they race, the later-starting one can
commit first and the other then lands just below it; a reader paging at that
moment sees it on the next reload.

Never in the history: a screening answer or which sensitive question changed, a
narrative, a record's explanation, evidence details or the named role, a rule
condition, private source references, credentials.

## 5. Web

The workspace gains a **Decisions & history** section (centre column, after the
answers; linked from the header):

- "What a record is, and isn't" (the API's wording) and "Holds and limits on
  this case": the intake hold, unresolved specialist reviews and the
  progression gate, each saying a record doesn't change it;
- **Employer records**: one card per chain showing the current version
  (category, summary, date, responsible, evidence, recorded by, explanation,
  "your company's account, not verified"), with **Correct** and **Add
  clarification**; earlier versions in a disclosure, marked "Replaced";
- the form (one at a time; a correction starts from the version it replaces):
  category, summary, date, responsible (and role), explanation, evidence status
  and references, and for a correction the reason. The browser checks it first;
  the API decides. A retry after a lost response reuses the request key;
- **Case history**: the unified timeline with a legend, a badge for each
  entry's nature and status, and "Show older entries".

The right panel no longer repeats the two per-source histories when the API
sends the unified one (it links to it). Against an older API (no `decisions` or
`timeline` block) the section says records aren't available and the right panel
keeps the earlier histories.

BFF: `POST /bff/companies/{id}/cases/{case}/decisions`,
`POST /bff/…/decisions/{record}/corrections` (the shared CSRF, content-type,
size and session guard; bodies rebuilt field by field; only safe categories)
and `GET /bff/…/history?before=…` (same-origin and session checks; the cursor
validated; nothing else accepted).

## 6. Persistence (migration D4, `c4a7e2d9b310`)

One append-only table, `workflow_decision_records`: id, `company_id`,
`instance_id`, `chain_id`, `supersedes_id`, `relation`, `category`, `summary`,
`explanation`, `occurred_on`, `decision_maker`, `decision_maker_role`,
`evidence_status`, `evidence` (JSONB references), `change_reason`, `revision`
(the instance revision the record produced), `request_key`,
`recorded_by_user_id`, the workflow context (`definition_version`,
`intake_status`, `progression_status`; codes only) and `recorded_at`.

- Company-qualified foreign keys to the instance and, for a correction, to the
  superseded record of the same chain (§3.5); the user; the Company (cascade,
  like every tenant table). No cascade from instances (PRIV-020).
- Unique: one row per request key per instance (idempotency), one row per
  instance revision, one successor per record.
- CHECK constraints: the vocabularies, the shape of a first record and of a
  correction, the decision-maker shape, text bounds and no control characters,
  evidence shape and bounds (held ⇔ at least one reference, at most 10, at most
  8 KiB), the date window, revision and definition version.
- RLS `tenant_isolation`; the API role may only SELECT and INSERT; the identity
  operator gets nothing; Supabase API roles are refused by the migration's
  guard.
- `heroos_schema_contract()` = 7. The M2-04 API needs at least 7; the operator
  CLI exactly 7.
- **Deploy order:** D4 → API and operator CLI → web. The M2-03 API keeps working
  on D4; the M2-04 API refuses to start on D3. The web tolerates an API without
  the new blocks. Rollback: the web at any time; the API to M2-03 at any time
  (it ignores the table); D4 only while the table is empty (rehearsed in
  `make e2e-check`, MIG-48 to MIG-53).

A record is a Case write: it takes a revision, so an answers form or a
progression request read before it is refused as stale (409) and asks the
employer to reload, exactly as any other concurrent change does.

## 7. HTTP contract

| Method and path | Notes |
| --- | --- |
| `GET /companies/{id}/workflows/{key}/decision-categories` | The safe categories, decision-maker and evidence choices, limits and the notices |
| `GET /companies/{id}/cases/{case}/decisions` | Every version, newest first, with version, current, superseded-by and the context |
| `POST /companies/{id}/cases/{case}/decisions` | `{expected_revision, request_key, category, summary, explanation, occurred_on, decision_maker, decision_maker_role?, evidence_status, evidence[]}` → the Case view (`decisions.saved` names the record) |
| `POST /companies/{id}/cases/{case}/decisions/{record}/corrections` | The same, plus `relation` (`correction`/`clarification`) and `change_reason` |
| `GET /companies/{id}/cases/{case}/history?limit=&before=` | A page of the unified history, newest first, with `next_before` and `total` |
| `GET /companies/{id}/cases/{case}/workflow` | Adds `decisions` and `timeline` (its first page) |

All administrator-only (`CompanyAdminDb`: the role is checked at authorization
and again in the transaction), reads included. Each write locks the instance,
answers a replay of its request key first (the same request, by the same
administrator, with the same content; a key reused otherwise is 409), then
checks the record being corrected (404 unless it belongs to this Case), the
revision (409 if stale) and that it is the current version (409), and commits
the row atomically; the database's unique keys are the backstop. 403 for a
member or another Company's path; 404 for a Case or record outside the
authorized Company (identical to a random id); 422 with field locations only.
Logs carry the Company and the relation only, never a category, text or
reference.

## 8. Privacy and safety

- Synthetic data only in tests, fixtures, screenshots and demos.
- The form asks for a role rather than a name, a summary rather than every
  allegation, and no health details; nothing sensitive is required.
- No upload, no link, no fetch, no parsing, no copy of evidence.
- The screening restrictions are unchanged; the history never repeats a
  screening answer.
- Retention and deletion of decision records are undecided (PRIV-001, PRIV-002,
  PRIV-005, PRIV-020): nothing is deleted, no schedule is implied, and D4 can't
  be downgraded once a record exists.

## 9. Open decisions (JJ and Technical Lead)

1. Approved customer wording for the categories, the notices and the history
   labels, and whether more factual categories are needed.
2. Which recorded decisions later become **inputs** to approved rules (for
   example, whether a recorded meeting can satisfy a stage requirement), and
   which need evidence; until approved rules say so, no record is ever an input.
3. Whether a named decision-maker may be a person's name, or must stay a role.
4. Whether evidence files will be uploaded later (object storage exists; the
   retention of uploads is PRIV-004) and how references then link to them.
5. Retention, deletion and legal hold for decision records and the history
   (PRIV-001, PRIV-002, PRIV-005, PRIV-016, PRIV-020).
6. Who may correct a record made by another administrator (today any
   administrator of the Company may; every version keeps its own actor).

## 10. Not in M2-04 (first slice)

Warning, suspension or dismissal letters and any document template; penalty
recommendations or outcome decisions; specialist approval or hold release;
evidence uploads; email; e-signatures; retention or deletion jobs; AI of any
kind; Probation and Recruitment; AWS. Document templates and safe previews are
the next M2-04 slice ([Document Templates and Safe Previews](document-templates.md));
a decision record never makes a template available.
