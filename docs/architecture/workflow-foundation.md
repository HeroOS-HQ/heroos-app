# Workflow Case Foundation (M2-01)

**Status:** Implemented (M2-01, PR #29, deployed to temporary staging). Extended by
M2-02: [Disciplinary Intake](disciplinary-intake.md), M2-03:
[Workflow Progression](workflow-progression.md) and M2-04:
[Decisions and Case History](workflow-decisions.md).\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform\
**Related:** [ADR-006](../decisions/ADR-006-workflow-orchestration.md),
[Tenant Isolation](tenant-isolation.md), [Delivery Plan](../milestones/delivery-plan.md)

## 1. What M2-01 is

The first vertical slice of the guided Disciplinary workflow, without AI:

1. a Company administrator opens a Company workspace and selects **Disciplinary**;
2. sees the Company's Disciplinary Cases and creates one;
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
- `heroos_schema_contract()` = 4 after D1, 5 after D2 (M2-02), 6 after D3
  (M2-03), 7 after D4 (M2-04). The current API needs at least 7; the identity
  operator CLI needs exactly 7. **Deployment
  order:** apply the migration, then deploy the API and the operator CLI, then
  the web app. The M1-10C API keeps working on D1 and the M2-01 API on D2
  (rehearsed in `make e2e-check`, MIG-30 to MIG-41).

## 3. Definitions, progress and conversation (`app/workflows/`)

- **Definitions are versioned code** (`definition.py`): steps and structured
  questions with neutral, authored text. A Case records the definition version
  it started with; a later version serves it only if it declares that version
  compatible (v2 keeps v1's questions unchanged and adds the M2-02 intake
  steps). Disciplinary v1 has one step, `initial_facts`: what happened
  (free text, ≤ 4,000 characters, stored as written), when (date or "not sure"),
  new or previously raised, discussed with the employee, evidence available
  (yes / no / not sure; no upload).
- **Validation** (`answers.py`) never normalizes and never echoes values in
  errors. `null` clears an answer.
- **Progress** (`progress.py`) is recomputed on every read from the stored facts
  and the Company's current jurisdiction assessment (operator confirmation can
  change it at any time). Steps: Case created → Initial facts (needs
  information / in progress / completed) → Jurisdiction (completed or blocked)
  → Assessment, decisions and documents (coming later). In M2-01 the Case
  status was one of `case_created`, `initial_facts_in_progress`,
  `awaiting_jurisdiction`, `jurisdiction_unsupported`, `initial_facts_completed`;
  since M2-02 progress and status come from the intake evaluation
  ([Disciplinary Intake §5](disciplinary-intake.md#5-safety-screening-holds-and-the-gate)).
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
| `GET /companies/{id}/workflows/{key}/cases` | `company_admin` | Summaries with status and progress counts, most recently active first |
| `POST /companies/{id}/workflows/{key}/cases` | `company_admin` | `{title, request_key}`; 201 created, 200 for a retry with the same key and title, 409 for a reused key with other details |
| `GET /companies/{id}/cases/{case}/workflow` | `company_admin` | Definition, current answers, missing questions, progress, status, jurisdiction readiness, conversation, `can_edit` |
| `PUT /companies/{id}/cases/{case}/workflow/steps/{step}/answers` | `company_admin` | `{expected_revision, submission_key, answers}`; 409 if stale or if the step can't be answered in the Case's current state (M2-02); a retry with the same `submission_key` is applied once (checked before anything state-dependent) |

- **Access policy (M2-01, interim least privilege until JJ approves dedicated
  HR access roles):** Disciplinary Cases are for **Company administrators
  only**: listing, opening, creating and answering. Every workflow route uses
  `CompanyAdminDb` (the role is checked at authorization and again inside the
  request's transaction), so a member gets the same fixed 403 everywhere and
  no title, answer, message or workflow metadata. The generic Case record
  routes (`GET /companies/{id}/cases[/{case}]`) leave restricted types out of a
  member's list and answer 404 for one (`app/workflows/access.py`). The web app
  never requests case data for a non-administrator and shows an
  "administrators only" state; the Disciplinary card on the workspace home is
  not a link for members. Blueprint and Company permissions are unchanged.
- **Concurrency:** a save locks the Case's instance row first
  (`SELECT … FOR UPDATE OF workflow_instances`), so concurrent saves of one
  Case run one after the other and every read in a request (replay check,
  revision check, current facts) sees one committed state. The revision bump
  remains a compare-and-set `UPDATE` as a second guard; exactly one of several
  saves against the same revision wins. Concurrent creations with one
  `request_key` produce one Case (unique key, the loser replays). Proven on
  PostgreSQL with real threads, including a deterministic regression test.
- **CI finding (PR #29, run 38777691679):** before the lock, an identical save
  committed by another request between this request's instance read and its
  replay check made this request replay with the revision it had read earlier:
  a 200 whose revision was older than the answers it returned, so the next save
  would have been refused as stale. No data was ever written twice or crossed a
  Company; the lock removes the window.
- Errors follow the Company routes: 403 for another Company or a member writing,
  404 for a Case outside the authorized Company (identical to a random id), 422
  with field locations only.

## 5. Web (`apps/web`)

> Since M2-NEW-02 the signed-in pages are JJ's approved Ask HeroOS, Company
> Blueprint and Company Space ([Signed-in Workspace](signed-in-workspace.md)):
> the routes and layout below are the M2-01 record.

- Routes: `/workspaces/[companyId]/cases` (list), `/cases/new` (create),
  `/cases/[caseId]` (guided workspace). The workspace home's Disciplinary card
  links to the list and says "Initial facts only"; Probation and Recruitment
  remain "Coming soon".
- Since the company workspace redesign (JJ design review screens 06–10,
  user-selected, JJ review pending), every page of one Company shares a
  full-width frame (`components/app/company-frame.tsx`): the header with the
  Company's name (or the switcher when the account has several), sign-out, and
  a navigation of the Company's real routes: Dashboard, Company Blueprint
  (`/settings`), HR Services (`/hr-services`), Cases (administrators only) and
  "Team & Access" shown as coming soon, never a link. `/hr-services` lists the
  three V1 workflows with their availability; `/disciplinary` (administrators;
  members get the "administrators only" state) explains what the product does,
  what waits for a confirmed jurisdiction, and the recent Cases. The case list
  has a search by title or id and a filter by the statuses the Cases have; both
  work on the list the page received. The review mockups' pathway stages,
  employee fields and document actions are not shown: they are illustrative and
  not approved.
- BFF mutations (same CSRF, content-type, size and session guard as M1-10D):
  `POST /bff/companies/{id}/workflows/{key}/cases` and
  `PUT /bff/companies/{id}/cases/{case}/steps/{step}/answers`. Bodies are rebuilt
  field by field; responses carry fixed codes.
- The guided workspace: case list (left), conversation and composer (centre),
  progress, jurisdiction readiness, known facts, missing information and "not
  available yet" (right; below the conversation on smaller screens). Members see
  an "administrators only" state instead. Double submission is prevented in the
  client and made harmless by the idempotency keys; a stale save asks the
  employer to reload.

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
case-history/audit timeline, deletion. M2-02 added the intake, the first
conditions, jurisdiction routing, the safety screening, holds and the case
history ([Disciplinary Intake](disciplinary-intake.md)); the rest is later M2
work.
