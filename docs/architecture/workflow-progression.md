# Workflow Progression and Private Rule Bundles (M2-03)

**Status:** Implemented (M2-03), not deployed. The generic engine, the D3
migration, the API and the web workspace are in this repository; the business
rules they run are **not**: they arrive as a private rule bundle (§3). No
genuine bundle is installed in any shared environment yet, so progression there
is unavailable (fail closed) until one is approved and installed (§4).\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform ("Prevent skipped HR steps")\
**Related:** [Workflow Case Foundation](workflow-foundation.md) (M2-01),
[Disciplinary Intake](disciplinary-intake.md) (M2-02),
[Decisions and Case History](workflow-decisions.md) (M2-04),
[Tenant Isolation](tenant-isolation.md), [ADR-006](../decisions/ADR-006-workflow-orchestration.md),
[Document Templates and Safe Previews](document-templates.md) (M2-04C: templates are bound to this bundle's stages)

## 1. What M2-03 is

A server-authoritative progression engine that keeps an employer from skipping
required steps of a guided workflow, without deciding anything for them. A
Company administrator, in the existing Disciplinary workspace:

1. sees the intake state (M2-02) and, once it is recorded, the next steps;
2. records a **pathway** as their own judgement: *Less serious*, *Serious
   misconduct* or *Unable to determine: needs review*;
3. sees the stages of that pathway, which one is in progress and which can
   start next;
4. answers the checklist of the stage in progress (Yes / No / Not sure);
5. asks to start or complete a stage, and is told exactly why not when the
   rules refuse (what is missing, or that specialist review is needed);
6. corrects answers at any time (append-only; nothing earlier is erased);
7. finds the position, the choices and every refusal again after a reload or a
   new sign-in, in an auditable progression history.

HeroOS never classifies the incident, suggests or validates a pathway,
recommends a sanction, generates a document or ends anyone's employment. A
transition being *allowed* means only that the installed rules found no
blocker: it is never presented as legal approval.

## 2. The engine (`app/workflows/progression/`)

Generic and reusable (Probation and Recruitment can use it with their own
pathways and bundles). Pure functions: the same bundle, intake evaluation,
answers and stored events always give the same result.

| Module | Role |
| --- | --- |
| `predicates.py` | Typed conditions: `answer … in`, `all`, `any`, `not`, `stage_completed`. Three-valued (Kleene) logic: unanswered and "Not sure" are UNKNOWN, never "No". Parsed from JSON; nothing is ever executed from text |
| `bundle.py` | The bundle schema, strict validation and the pinned loader (§3) |
| `spec.py` | Public per-workflow vocabulary: the employer's pathway choices and what is still not built |
| `engine.py` | The state machine: position, offered transitions, decisions |
| `presentation.py` | Generic customer wording for statuses, engine gates and history (bundle rules carry their own) |
| `records.py` | A stored progress event as the read path sees it |

**Position** is derived from the append-only progress events (§5), never
stored as a mutable snapshot: the latest pathway choice, the stage in
progress, the stages completed in order, and, once a terminal stage is
completed, the end of the workflow. A pathway change leaves the stage in
progress without completing it; completed stages and all answers stay.

**Transitions** are offered from the current position only:

- `pathway:<key>`: record another pathway (until the workflow ends);
- `start:<stage>`: start one of the next stages of the current pathway (its
  entry stages, or the successors of the stage completed last);
- `complete:<stage>`: complete the stage in progress.

Anything else that names a known stage or pathway (a later stage, another
pathway's stage, a completed stage, completing a stage that isn't in progress,
the current pathway again) is **refused and recorded** as not available from
the current position. That is how skipping is prevented. An unknown key is 404.

**Decisions** use a fixed precedence over all results of a transition:

| Decision | Meaning |
| --- | --- |
| ESCALATE | Refused; the need for specialist review is recorded. Sticky per transition: once recorded, changed answers never release it (no release exists, §8) |
| BLOCK | Refused; the reasons say what is missing or why it isn't available |
| WARN | Allowed only when the employer acknowledges exactly the cautions shown (a mismatch is a 409). Never overrides a block or an escalation |
| ALLOW | No rule fired |

`ESCALATE > BLOCK > WARN > ALLOW`. A rule fires unless its condition is
definitely false: `require: P` fires unless P is true, `when: P` fires unless P
is false. An unknown input therefore always fires the rule (no false
negative); an escalating rule whose inputs are unknown **blocks for missing
information** instead, and is never recorded as an escalation until its
condition is actually met.

**Engine gates** apply to every transition before any bundle rule:

| Gate | Decision | When |
| --- | --- | --- |
| `rules_unavailable` | block | No bundle installed: nothing is offered and every write is refused (409) |
| `rules_version_incompatible` | block | The Case's events were decided under a bundle version the installed one doesn't declare compatible (§3) |
| `case_held` | escalate | The intake holds the Case for specialist review (M2-02; sticky) |
| `jurisdiction_paused` | block | The intake is paused until the jurisdiction is confirmed |
| `intake_incomplete` | block | The intake gate is closed: a screening that is disabled, incomplete or "Not sure" never counts as cleared |
| `jurisdiction_not_covered` | block | The bundle has no program for the Case's jurisdiction. Another jurisdiction's rules are never used instead |
| `workflow_closed` | block | A terminal stage was completed |

While a gate applies to the whole Case only its own explanation is shown (no
bundle guidance is offered for a held Case), and stage checklists can't be
answered.

## 3. Private rule bundles

JJ's methodology (stage prerequisites, legal and jurisdiction rules, source
mappings, customer wording) is proprietary and stays out of this public
repository. The engine runs a **rule bundle**: a small, versioned, declarative
JSON document (schema `heroos.rule-bundle/1`, documented in `bundle.py`):

- per jurisdiction, the pathways that have stages; per pathway, its entry
  stages and stages; per stage, its title, summary, checklist items, successor
  stages, whether it is optional or terminal, and the rules for starting and
  completing it; optional rules for selecting the pathway;
- every rule: a key, an action (`warn` / `block` / `escalate`), a `require` or
  `when` condition, whether its content is still under review (`provisional`:
  shown as such, never as approved advice), and its customer wording;
- `provenance`: `private` (real content) or `synthetic` (fictional test
  content; refused in production; always announced on every Case it serves);
- `version`, `serves_versions` (earlier versions whose Cases it may continue)
  and `definition_versions` (the question definitions it was written for).

**Conversation rules** (M2-NEW-06, optional `conversation` section): typed
facts no definition question owns, and per jurisdiction the rules an
execution profile may bind to a knowledge Condition, and each employer
decision's mandatory-prerequisite rules. They may compare whole numbers
(`{"compare": key, "op": "gt", "value": n}` or `"field": other`) and carry a
`follow_up` (`employer_insists`: a two-state caution; `condition_specific`:
its own predicate). They never read a sensitive answer or a stage. A stage
rule can't compare numbers. A conversation rule only ever translates a rule
the approved HeroOS content already states unambiguously; the Technical Lead
may approve that translation, and anything missing, ambiguous or new waits for
the product, domain or legal authority. See [conversation-evaluation.md §14.1](conversation-evaluation.md#141-who-approves-what).

**Validation** (strict; the API refuses to start on any failure): exact fields
only, no duplicate JSON keys, no NaN/Infinity, bounded sizes and text, known
pathways, an acyclic stage graph with every stage reachable from an entry,
terminal stages without successors, unique stage and rule keys, no stage
shadowing an intake step, every condition reading only a known answer
(intake questions or the bundle's own checklists) and never a **sensitive**
screening answer, and a start rule never reading its own stage's checklist.
Refusals carry a fixed code and a structural location (indexes), never content.

**Loading contract** (`HEROOS_RULE_BUNDLE_PATH` and `HEROOS_RULE_BUNDLE_SHA256`,
set together; absolute path; lowercase hex pin):

| Configuration | Result |
| --- | --- |
| Neither set | API starts; progression unavailable (fail closed); intake unaffected |
| Both set, file valid and matching the pin | Loaded once at startup into memory; never re-read while running |
| File missing, unreadable, changed (pin mismatch), invalid, for another definition, or synthetic in production | **Startup refused** (fixed code in the log). Nothing falls back to other rules |

The browser never receives a bundle: only the API's per-Case answer (titles,
checklist prompts and the messages of rules that fired for that Case). The web
app has no access to the file, and a test proves no rule content is in the web
build's assets. The API image copies only `apps/api/app`, so the synthetic test
bundle (`apps/api/tests/fixtures/rule_bundles/`) is never in it.

**Versions.** Every progress event stores the bundle id, version and content
digest. A Case continues under a newly installed bundle only if it is the same
version or the new one lists the old in `serves_versions`; otherwise the Case
is paused (`rules_version_incompatible`) rather than re-evaluated under
different rules. Rolling back to an older bundle pauses Cases that already used
the newer one.

**Repository guards:** `*.private-bundle.json` and `private-rule-bundles/` are
git-ignored; a test fails if any tracked or new file in the repository is a
bundle with `provenance: private`. (`.gitignore` does not protect a file that
was already committed: never commit one.)

**Validation tool:** `uv run python -m scripts.rule_bundle validate PATH
[--production]` (from `apps/api`) runs the startup checks and prints the pin,
the content digest and coverage counts, never wording or conditions.

## 4. Providing the bundle in deployed environments

Not done: installing a genuine bundle anywhere is a JJ content approval plus a
Technical Lead deployment decision.

**Authoring (private).** The bundle source and its source-traceability mapping
live outside this repository (a private, access-controlled content location;
today the Technical Lead's private records). A release is one JSON file plus
its SHA-256, validated with the tool above, with JJ's approval recorded
alongside.

**Temporary staging (Render).** Render *Secret Files* are made available only to
the service at runtime (`/etc/secrets/<name>`), are not in Git or the image,
and are managed in the dashboard. Proposed procedure: upload the approved file
as a secret file; set `HEROOS_RULE_BUNDLE_PATH=/etc/secrets/<name>` and
`HEROOS_RULE_BUNDLE_SHA256=<pin>`; deploy; confirm the startup log line
(`rules loaded … version=…`) and a smoke check. This uses an existing service
feature (no new infrastructure) but places proprietary content with a vendor:
it needs explicit approval first.

**AWS (M4/M5).** Recommended: a private S3 bucket (SSE-KMS, versioning, Block
Public Access, a bucket policy granting read to the API task role only),
fetched at container start into a tmpfs path, with the pin in the task
definition; access logged in CloudTrail. To be recorded in an ADR when the AWS
environment is built.

**Rotation and rollback.** Change the file and the pin together; a new version
that continues existing Cases declares them in `serves_versions`. Unsetting both
variables makes progression unavailable again; stored events and history stay
readable.

## 5. Persistence (migration D3, `8d217d768395`)

One append-only table, `workflow_progress_events`, written in the same
transaction as the decision it records and under the same instance lock as
every other workflow write:

| Kind | Written when | Request key | Revision |
| --- | --- | --- | --- |
| `pathway_selected` | A pathway choice is recorded (with the previous choice) | yes | New (bumps the instance revision) |
| `stage_started`, `stage_completed` | The employer moved the Case on | yes | New |
| `transition_rejected` | The rules refused a requested transition | yes | Unchanged (nothing moved) |
| `escalation_recorded` | A rule first escalates an offered transition (on any write: an answer save, a checklist save or a transition) | no | The revision it was decided at |

Each row holds the decision, its results as codes (engine gate codes and rule
keys with their outcome and, for unknown inputs, the question keys; never an
answer or free text), the acknowledged warnings, the actor, the intake status
at the time and the bundle id, version and digest. The database refuses
malformed events (kind/decision shape, vocabularies, key formats, a bounded
trace), allows one position change per instance revision and one row per
request key. Company-qualified foreign keys to the instance and (for an
escalation found by a save) the submission; RLS `tenant_isolation`; the API
role may only SELECT and INSERT; the identity operator gets nothing.
`heroos_schema_contract()` = 6. Downgrade refuses once any event exists.

Stage checklists reuse the existing storage: they are saved through the step
answers route as `workflow_submissions` + `case_facts` under keys
`progress.<stage>.<item>` (append-only, correctable), and each save keeps the
M2-02 invariant of one intake evaluation per submission.

**Deploy order:** D3 → API and operator CLI → web. The M2-02 API keeps working
on D3; the M2-03 API refuses to start on D2; the M2-03 operator CLI needs
contract 6 exactly (since M2-04 and D4: 7, see
[Decisions and Case History §6](workflow-decisions.md#6-persistence-migration-d4-c4a7e2d9b310)). The web tolerates an API without the `progression` block (it shows
that next steps aren't available). Rollback: the web at any time; the API to
M2-02 at any time (it ignores the new table); D3 only while it is empty
(rehearsed in `make e2e-check`, MIG-42 to MIG-47).

## 6. HTTP contract

| Method and path | Notes |
| --- | --- |
| `GET /companies/{id}/cases/{case}/workflow` | Adds `progression`: status, gate, rules (bundle, version, provenance, notice), the recorded pathway, the pathway options with their decisions, the stages and their status, the stage transitions offered now (decision, reasons, cautions to acknowledge, missing answers), the checklist of the stage in progress, unresolved escalations, what's not available yet, the progression history, and `attempt` (on write responses: what happened to that request) |
| `POST /companies/{id}/cases/{case}/workflow/progression/pathway` | `{expected_revision, request_key, pathway, acknowledged_warnings}` |
| `POST /companies/{id}/cases/{case}/workflow/progression/transitions` | `{expected_revision, request_key, transition, acknowledged_warnings}`; only `start:` / `complete:` keys |
| `PUT /companies/{id}/cases/{case}/workflow/steps/{stage}/answers` | The existing answers route also saves the checklist of the stage in progress (409 for any other stage) |

All administrator-only (`CompanyAdminDb`: the role is checked at authorization
and again inside the transaction). Each write locks the instance
(`SELECT … FOR UPDATE`), answers a replay of its request key first, then
checks the revision, evaluates every condition, and commits the outcome and
its events atomically. 200 for an applied **or refused** transition (the
`attempt` says which); 404 for an unknown Case or transition; 409 for a stale
revision, a request key reused for another transition, acknowledgments that
aren't exactly the cautions shown, or no installed or matching rules; 422 for
malformed input. Errors never echo input or rule content; logs carry the event
kind, the decision and the Company only.

## 7. Web

The existing three-column workspace gains a **Next steps** section between the
conversation and the answers composer: the synthetic-rules notice where
applicable, the gate explanation, the pathway decision card (the employer's own
choice; HeroOS suggests nothing), the stage list with the current stage, the
actions the API would accept (a button) or refuses (the reasons, what is still
needed, and "specialist review needed" for an escalation, never a button), the
checklist form, unresolved specialist reviews, and the outcome of each
request. The header shows the current stage. The progression history was shown
in the right panel; since M2-04 it is part of the unified case history under
“Decisions & history” ([Decisions and Case History §5](workflow-decisions.md#5-web)). Two BFF routes (`/bff/companies/{id}/cases/{case}/progression/pathway`
and `…/transitions`) use the shared CSRF, content-type, size and session guard
and rebuild the body field by field. The parser never treats a refused
transition as available, whatever the payload says.

## 8. Open decisions (JJ and Technical Lead)

1. Approval of the genuine (private) bundle content, its review status per rule
   and its customer wording; where its source-traceability record lives.
2. Where the bundle is stored for staging (Render secret file) and for AWS.
3. Unresolved process questions recorded privately with the bundle draft
   (e.g. whether some steps may be skipped, and which outcomes need specialist
   review); until decided, the draft blocks or escalates them.
4. Who may release a specialist-review escalation (intake or progression) and
   how: no release exists; nothing is ever released by changed answers.
5. Retention and deletion of progress events and checklist answers
   (PRIV-001 to PRIV-005, PRIV-020); nothing is deleted.
6. DIFC progression content; until approved, DIFC Cases have no program and
   remain held at intake.

## 9. Not in M2-03

Document generation, penalty or outcome decisions, termination, expert
tickets or clearance, deadline tracking, cross-case history, AI of any kind,
Probation and Recruitment content, AWS deployment.
