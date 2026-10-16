# Disciplinary Intake, Jurisdiction Routing and Safety Screening (M2-02)

**Status:** Implemented (M2-02, PR #30, merged as `80adbae`). Deployed to the
temporary staging environment for controlled testing with the sensitive
screening **disabled** (§7.1). Development content: not legally approved.\
**Owner:** Technical Lead\
**Milestone:** M2 — Workflow Platform\
**Related:** [Workflow Case Foundation](workflow-foundation.md) (M2-01),
[Tenant Isolation](tenant-isolation.md), [ADR-006](../decisions/ADR-006-workflow-orchestration.md),
[Privacy Decision Register](../privacy/decision-register.md)

## 1. What M2-02 is

The first deterministic intake of the Disciplinary workflow, without AI. A
Company administrator opens a Disciplinary Case (new, or created under M2-01)
and, in the same guided conversation:

1. answers or corrects the M2-01 initial facts (unchanged);
2. confirms the Case's employment jurisdiction against the Company's
   operator-confirmed jurisdiction;
3. gives the incident context (asked only where relevant);
4. answers the safety screening (Yes / No / Not sure), where the environment
   enables it (§5);
5. sees what is missing or uncertain, any caution, any hold, and the Case
   history.

Nothing here classifies the incident, assesses the employee, recommends a
sanction or generates a document. A cleared intake is a **preliminary status**
(`intake_recorded`), not a legal assessment: it only opens the gate later stages
(not built yet) must check (`IntakeEvaluation.next_stage_open`).

## 2. Rules and their content

`app/workflows/conditions.py` is a small, generic rule engine: rules are typed
data evaluated with three-valued logic (an unanswered question and "Not sure"
are unknown, never "No"); nothing is executed from text. The rule set
(`disciplinary-intake.1`) has five rules, run in order:

| Rule key | Applies in | Action | Provisional | Reads | Effect |
| --- | --- | --- | --- | --- | --- |
| `case_jurisdiction` | every Case, first | block, or escalate | no | Company readiness, Case confirmation | §4 |
| `policy_awareness` | UAE Federal | warn | yes | incident context | Caution |
| `same_incident_sanction` | UAE Federal | warn | no | incident context | Caution |
| `off_duty_connection` | UAE Federal | warn | no | incident context | Caution |
| `high_risk_screening` | UAE Federal | escalate | yes | safety screening | Hold for specialist review |

- A rule runs only if it is enforced and applies in the resolved Case
  jurisdiction. A UAE Federal rule never runs for a DIFC Case.
- "Provisional" rules are still under legal review: their cautions and holds
  are tagged "Provisional: not legal advice", never presented as approved.
- The rule set's version and SHA-256 digest are stored with every evaluation,
  so the trace shows exactly which rules ran.

The rule content is development content from HeroOS's private content library.
Which library entries, versions and review statuses each rule corresponds to
is recorded privately with the M2-02 records, not in this public repository
(§8).

Tests: `tests/workflows/test_intake.py` (predicates, rule set and digest,
routing, screening, holds, cautions, trace), `tests/auth/test_intake_api.py`
(the routes), `tests/tenant_isolation/test_workflow_cases.py` (PostgreSQL),
e2e `intake` (browser and API).

## 3. Interpretations kept for review

The engine takes the more restrictive reading where a rule leaves room:

1. Routing: unclear → block (ask the employer to confirm); conflicting or
   unsupported → escalate.
2. A resolved jurisdiction without screening (DIFC today) is held for
   specialist review: never screened with another jurisdiction's rule and
   never left unscreened.
3. The off-duty caution triggers when no connection to work is *stated*:
   "Not sure" counts with "No"; unanswered is unknown.
4. The earlier-sanction caution is shown at intake, from the employer's answer.
5. While a Case is held for specialist review, cautions are evaluated and
   recorded but not shown.
6. A specialist-review hold is never released by changed answers (§5).

## 4. Jurisdiction routing

The Company Blueprint holds one operator-confirmed `employment_jurisdiction`
and its readiness (`app/companies/jurisdiction.py`); it has no list of
operating jurisdictions. With no second jurisdiction system:

- The Case question `jurisdiction.case_confirmation` is asked only when the
  Company's jurisdiction is confirmed and supported. Its options are built by
  the server from that confirmation ("Yes, ⟨Company jurisdiction⟩", "No, a
  different jurisdiction applies", "Not sure"). A Case can never pick a
  jurisdiction the Company's confirmation doesn't support (422).
- The stored answer is the jurisdiction code it confirmed; if the operator
  later confirms a different one, the old answer no longer matches and the
  Case is paused until it is confirmed again.
- The basis is recorded on every save (the routing result's inputs: Company
  readiness, reason and jurisdiction, and the Case answer).
- Unconfirmed, unclear, conflicting or unsupported → no jurisdiction-dependent
  step can be answered (409) and no jurisdiction-specific rule runs. No UAE
  Federal wording reaches a DIFC Case (API tests, e2e INTAKE-12).

## 5. Safety screening, holds and the gate

**Sensitive data.** The screening asks Yes / No / Not sure about health-related
and other legally sensitive circumstances (for example pregnancy, sick leave, a
medical condition). No privacy basis or retention policy is approved for these
answers yet, so:

- The API setting `HEROOS_SENSITIVE_SCREENING` is `disabled` by default and in
  production (startup refuses anything else there). Only an environment that
  holds synthetic demo data only may set `synthetic_demo`.
- When disabled, the screening step can't be answered (409), stored screening
  answers are never evaluated, and no intake can be completed (status
  `screening_unavailable`).
- When `synthetic_demo`, the case page says it's a demo environment and the
  screening asks for made-up examples only.
- Only the enumerated answer is stored (`case_facts`, append-only). The
  evaluation trace keeps counts only (how many Yes / No / Not sure /
  unanswered), and the case history says how many screening answers changed,
  never which. Answers are shown only to Company administrators, never logged
  (API logs carry the hold kind only) and never echoed in errors.

**Holds.**

- Positive (any Yes) → hold `specialist_review` (escalate, provisional). The
  hold names the factors in plain words, says a Yes isn't a finding about the
  employee, and says HeroOS doesn't offer expert review in the app yet and
  hasn't contacted anyone. **No ticket is created**: a held save writes only
  the submission, its facts and its evaluation (proven on PostgreSQL).
- Not cleared (a Not sure, no Yes) → `screening_not_cleared`; the gate stays
  closed.
- **An escalation is never released by changed answers.** Once a save holds a
  Case for specialist review (high-risk answer, different or unsupported
  jurisdiction, no screening for the jurisdiction), every later evaluation
  keeps it held (`earlier_escalation`), whatever the answers change to. The
  view reports separately the current screening state and the first
  escalation (`intake.escalation`: since when, why, and whether the current
  answers still call for it). There is no release in the product: who may
  release a hold, and how, is undecided (§8).
- Answers stay saveable while held (they can be corrected; the history keeps
  every change). The gate stays closed while any hold is in force.

Statuses, highest first: `held_for_specialist_review` → `awaiting_jurisdiction`
→ `case_created` (nothing answered) → `intake_in_progress` →
`screening_unavailable` → `screening_not_cleared` → `intake_recorded`.

## 6. Persistence (migration D2, `e64497d997d8`)

- **`workflow_evaluations`** (append-only): one row per saved submission,
  written in the same transaction and under the same instance lock (the M2-01
  lock and revision checks are unchanged). It holds the status, hold and
  reason, resolved jurisdiction, screening state, every rule's result with the
  inputs it read (enumerated values; counts for sensitive questions; never
  free text) and the definition version, rule-set version and digest.
  Company-qualified foreign key to the submission, RLS `tenant_isolation`,
  runtime SELECT/INSERT only, nothing for the operator,
  `heroos_schema_contract()` = 5. Downgrade refuses once a row exists.
- There is no mutable status column: the current state is recomputed on every
  read (the Company's readiness can change at any time). The first escalation
  is read from the stored evaluations.
- **Case history** is composed from append-only rows only: the instance, the
  submissions (changed labels; counts for sensitive questions) and the
  differences between consecutive evaluations (jurisdiction confirmed, hold
  placed, kept or lifted — a jurisdiction pause can lift; a specialist-review
  hold is only ever kept — screening result, cautions, intake recorded).
- **Definition v2** keeps v1's initial-facts step unchanged and declares v1
  Cases compatible, so M2-01 Cases continue into the intake.

## 7. Deployment

Order: **D2 → API and operator CLI → web**, with `HEROOS_SENSITIVE_SCREENING`
left unset (disabled) unless the environment is confirmed to hold synthetic
demo data only.

| Window | Effect |
| --- | --- |
| D2 applied, M2-01 API running | Works (expand-only; M2-01 saves create no evaluation) |
| D2 applied, M2-01 operator CLI | Refuses to run (it needs contract 4 exactly): update the CLI with the API |
| M2-02 API on D1 (wrong order) | Refuses to start (contract 4 < 5); a platform that keeps the old instance on a failed health check keeps serving M2-01 |
| M2-02 API, M2-01 web | Works; the old web shows only the initial facts and miscounts the questions |
| M2-02 web, M2-01 API (wrong order) | Case pages can't load (the view lacks the intake fields); lists still load. If the web deploys automatically on merge, apply D2 and deploy the API first or immediately after |

Rollback: the web can roll back at any time. The API can roll back to M2-01
only until the first M2-02 Case exists (M2-01 can't serve definition v2: its
Disciplinary list and those cases fail). D2 can be downgraded only while
`workflow_evaluations` is empty, and only after the API is back on M2-01.
After that: roll forward.

### 7.1 Staging deployment record (2026-10-16)

| Step | Result |
| --- | --- |
| Pre-migration backup | Logical backup of the staging database at D1, validated by a full restore into a throwaway container (fingerprints identical) |
| Rehearsal | D2 applied to a restored copy of that backup, all checks passed; downgrade to D1 and re-upgrade rehearsed |
| D2 on staging | Applied 2026-10-16 11:44Z (`75ec6db8b6c1` → `e64497d997d8`, contract 5); existing data unchanged; RLS, policy, grants (runtime SELECT/INSERT only, nothing for the operator) and constraints verified |
| M2-01 API on D2 | Unauthenticated smoke test passed before the API rollout |
| Merge | PR #30 squash-merged as `80adbae` (tree identical to the reviewed head) |
| API (Render) | `80adbae` deployed manually by the Technical Lead (Auto-Deploy off; environment unchanged); smoke test passed |
| `HEROOS_SENSITIVE_SCREENING` | Not set on Render (confirmed by the Technical Lead): the screening is disabled |
| Web (Vercel) | Not deployed by the merge: Vercel's Hobby plan can't deploy a private organization repository, and the repository was private at the time. With the repository public again, the docs-only merge that adds this record triggers the Production deploy (app code identical to `80adbae`); its revision and verification are recorded in the deployment report |
| Browser acceptance | Pending at the time of writing: needs an administrator sign-in |

Operator CLI: after D2 it must run from code at or after `80adbae` (it requires
contract 5 exactly).

## 8. Open decisions (JJ)

1. Legal review of the two provisional rules.
2. Definitions used by the screening ("recently", "senior").
3. Whether screening may apply to DIFC Cases; until then they are held.
4. Who may release a specialist-review hold, and how (an expert workflow);
   until then holds are never released.
5. Privacy approval for the sensitive screening answers: legal basis,
   retention (PRIV-001 to PRIV-005), and whether to store per-question answers
   at all. Until then the screening is disabled outside synthetic demo
   environments.
6. Multi-jurisdiction Companies (a list of operating jurisdictions).
7. Approved customer wording for cautions and holds.
8. Where the rule content and its source mapping live: this repository is
   public, so content beyond these five rules should move to private,
   versioned content bundles loaded server-side.
