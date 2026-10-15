# Workflow Case Foundation (M2-01)

**Status:** Implemented on a feature branch (M2-01). Not deployed.\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform\
**Related:** [ADR-006](../decisions/ADR-006-workflow-orchestration.md),
[Tenant Isolation](tenant-isolation.md), [Delivery Plan](../milestones/delivery-plan.md)

## 1. What M2-01 is

The first vertical slice of the guided Disciplinary workflow, without AI:

1. an authorized user opens a Company workspace and selects **Disciplinary**;
2. sees the Company's Disciplinary Cases, creates one (Company administrators only);
3. opens it in a ChatGPT-style guided workspace and answers an initial
   structured question group;
4. leaves and comes back (reload, new sign-in): everything is read from
   PostgreSQL;
5. sees progress derived from the saved answers and the Company's live
   jurisdiction readiness, and a plain statement of what is **not** built yet.

Nothing in M2-01 classifies, assesses or decides anything. There are no
Conditions, no legal content, no documents and no expert workflow yet; the UI
says so. The authoritative content (JJ's Knowledge Library) and the analysis of
it are confidential and are **not** in this repository.

## 2. Model

ADR-006: the HeroOS workflow engine in PostgreSQL is the business-process truth.
M2-01 adds the smallest reusable part of it (migration `75ec6db8b6c1`, "D1"):

| Table | Purpose | API role |
| --- | --- | --- |
| `workflow_instances` | One guided workflow run per Case: `workflow_key`, `definition_version`, optimistic-concurrency `revision`, the creating request's `request_key`, `created_by_user_id` | SELECT, INSERT, UPDATE (`revision`, `updated_at`) |
| `workflow_submissions` | One saved answer group: `step_key`, the `revision` it produced, its `idempotency_key`, `submitted_by_user_id`, `submitted_at` | SELECT, INSERT |
| `case_facts` | The answers, versioned and append-only: `fact_key`, `value` (JSONB; NULL = cleared), linked to their submission | SELECT, INSERT |

- The existing `cases` row stays the Case (`case_type = disciplinary`, set by the
  server). `case_subjects` is not used yet: linking an employee is deferred.
- Every table follows [tenant-isolation §9](tenant-isolation.md#9-contract-for-future-private-entities-m2-and-later):
  explicit `company_id`, Company-qualified foreign keys
  (`(company_id, case_id)`, `(company_id, instance_id)`,
  `(company_id, instance_id, submission_id)`), RLS with the single
  `tenant_isolation` policy, scoped repositories, explicit grants.
- Append-only, no deletion: the API role cannot UPDATE or DELETE facts or
  submissions, cannot DELETE instances, and cannot delete a Case that has a
  workflow (the foreign key refuses). Deletion and retention are privacy
  decisions (PRIV-001/002/004/020), not technical defaults. Downgrading D1
  refuses once any workflow data exists.
- `heroos_schema_contract()` = 4. The API needs at least 4 (it refuses to start
  on C1); the identity operator CLI needs exactly 4. **Deployment order:** apply
  D1, then deploy the API and the operator CLI, then the web app. The M1-10C API
  keeps working on D1 (rehearsed in `make e2e-check`, MIG-30 to MIG-34).

## 3. Definitions, progress and conversation (`app/workflows/`)

- **Definitions are versioned code** (`definition.py`): steps and structured
  questions with neutral, authored text. A Case records the definition version
  it started with. Disciplinary v1 has one step, `initial_facts`: what happened
  (free text, ≤ 4,000 characters, stored as written), when (date or "not sure"),
  new or previously raised, discussed with the employee, evidence available
  (yes / no / not sure; no upload).
- **Validation** (`answers.py`) never normalizes and never echoes values in
  errors. `null` clears an answer.
- **Progress** (`progress.py`) is recomputed on every read from the stored facts
  and the Company's current jurisdiction assessment (operator confirmation can
  change it at any time). Steps: Case created → Initial facts (needs
  information / in progress / completed) → Jurisdiction (completed or blocked)
  → Assessment, decisions and documents (coming later). The Case status is one
  of `case_created`, `initial_facts_in_progress`, `awaiting_jurisdiction`,
  `jurisdiction_unsupported`, `initial_facts_completed`.
- **Conversation** (`conversation.py`) is composed from that state: welcome,
  the question group, each saved submission as the employer's turn followed by a
  neutral "Saved" acknowledgement, missing information, the jurisdiction notice
  and the "not available yet" notice. Facts are stored independently of this
  presentation, so a later presentation (or an M4 assistant that only phrases
  and proposes) can change without touching the data. Message types: information,
  question group, answer confirmation, missing information, status notice.

## 4. HTTP contract (`app/api/workflows.py`)

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /companies/{id}/workflows/{key}/cases` | any active member | Summaries with status and progress counts, most recently active first |
| `POST /companies/{id}/workflows/{key}/cases` | `company_admin` | `{title, request_key}`; 201 created, 200 for a retry with the same key and title, 409 for a reused key with other details |
| `GET /companies/{id}/cases/{case}/workflow` | any active member | Definition, current answers, missing questions, progress, status, jurisdiction readiness, conversation, `can_edit` |
| `PUT /companies/{id}/cases/{case}/workflow/steps/{step}/answers` | `company_admin` | `{expected_revision, submission_key, answers}`; 409 if stale; a retry with the same `submission_key` is applied once |

- **Write-authorization policy (M2-01):** creating Cases and saving answers is
  limited to Company administrators (`CompanyAdminDb`: checked at authorization
  and again in the write transaction). Reading follows the existing Case read
  policy (any active member). Whether members should see Disciplinary content
  at all is an open product/privacy question for JJ.
- **Concurrency:** the revision bump is one compare-and-set `UPDATE`; concurrent
  saves against the same revision serialize on the row lock and exactly one
  wins. Concurrent creations with one `request_key` produce one Case (unique key,
  the loser replays). Both are proven on PostgreSQL with real threads.
- Errors follow the Company routes: 403 for another Company or a member writing,
  404 for a Case outside the authorized Company (identical to a random id), 422
  with field locations only.

## 5. Web (`apps/web`)

- Routes: `/workspaces/[companyId]/cases` (list), `/cases/new` (create),
  `/cases/[caseId]` (guided workspace). The workspace home's Disciplinary card
  links to the list and says "Initial facts only"; Probation and Recruitment
  remain "Coming soon".
- BFF mutations (same CSRF, content-type, size and session guard as M1-10D):
  `POST /bff/companies/{id}/workflows/{key}/cases` and
  `PUT /bff/companies/{id}/cases/{case}/steps/{step}/answers`. Bodies are rebuilt
  field by field; responses carry fixed codes.
- The guided workspace: case list (left), conversation and composer (centre),
  progress, jurisdiction readiness, known facts, missing information and "not
  available yet" (right; below the conversation on smaller screens). Members get
  a view-only workspace. Double submission is prevented in the client and made
  harmless by the idempotency keys; a stale save asks the employer to reload.

## 6. Privacy and safety boundaries

- Only synthetic data in tests, fixtures and demos.
- Case titles and narratives never reach logs (request logs carry route
  templates only; 422 responses never echo input); checked in API tests and
  `make e2e-check` (CASE-17).
- The UI asks for neutral titles without the employee's full name and asks
  employers to leave out unnecessary personal details. No uploads.
- Nothing claims that retention, legal approval or expert review is settled:
  the screens say those stages are not available yet.

## 7. Not in M2-01

Conditions engine, classification, jurisdiction-specific guidance, employer
decisions, document generation, expert escalation, case-subject linking,
case-history/audit timeline, deletion. See the analysis report's sequence for
M2-02 onwards (kept outside the repository with the confidential sources).
