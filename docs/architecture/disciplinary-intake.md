# Disciplinary Intake, Jurisdiction Routing and Safety Screening (M2-02)

**Status:** Implemented on a feature branch (M2-02). Not deployed. Development
content: not legally approved.\
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
3. gives the incident context (work connection, documented earlier action,
   earlier sanction for the same incident, whether the expected standard was
   explained, witnesses);
4. answers the safety screening (nine high-risk factors, Yes / No / Not sure);
5. sees what is missing or uncertain, any caution, any hold, and the Case
   history.

Nothing here classifies the incident, assesses the employee, recommends a
sanction or generates a document. A cleared intake is a **preliminary status**
(`intake_recorded`), not a legal assessment: it only opens the gate later stages
(not built yet) must check (`IntakeEvaluation.next_stage_open`).

## 2. Sources and how they're used

The rules are mapped from JJ's Knowledge Library. Those files are confidential
and **not** in this repository; this repository is public, so it holds only
condition IDs, the metadata the workbook states for them, typed predicates,
source references (file, SHA-256, sheet and row, rule number) and neutral
wording written by engineering. The row-by-row mapping with source text is kept
privately with the M2-02 report.

| Source | File | SHA-256 | Version |
| --- | --- | --- | --- |
| Conditions Library | `HeroOS_Conditions_Library-13.xlsx` | `ee7cfe5afe0986b01febf6a7a8f225fa75596ec33d435aba2bad5f08fb0be57d` | workbook modified 2026-10-14T07:29:23Z |
| Implementation & AI Routing Rules | `HeroOS Aries Implementation Rules - 14-10.docx` | `de03a865e830b9cf0b32e93699e036a16fa6c1bd21c90dd5c9625211273d26eb` | working draft, revision 6, modified 2026-10-14T06:30:00Z |
| Conduct & Discipline Playbook 4C | `00 - HeroOS - 4C - Conduct & Discipline Playbook.docx` | `adfe99761ce5e0c232f76ee6fff5504981b24c32a5fedec1abd3170f33b91ec8` | revision 39 (read for context; no Playbook wording is shown) |

The rule set (`app/workflows/conditions.py`, version `disciplinary-intake.1`)
pins both hashes. Its SHA-256 digest covers every condition's metadata,
predicate, sources and the source hashes; every stored evaluation records the
rule-set version and digest it used, so a later change of any rule or source is
visible in the trace.

## 3. Implemented conditions (mapping and tests)

Evaluation order: the routing rule first (its own trigger text: it runs ahead
of every other condition), then the others in workbook row order. A condition
runs only when it is `active` and tagged with the resolved Case jurisdiction,
`SHARED` or `GLOBAL` (Implementation Rules §4, §7). No jurisdiction tag was
changed: the conditions the workbook marks "proposed SHARED" stay `UAE-FED`.

| Condition ID | Source | Tag | Type → action | Citation / enforcement | Engine behaviour | Unknown inputs | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `JURISDICTION-ROUTING-001` | CL "Conditions Library" R41; "Blueprint Fields" R11; "Structural Findings" R23, R25; IR §1–7, §17 | GLOBAL | precondition → block, or escalate (workbook action cell: "blocking") | confirmed / active | Resolves the Case jurisdiction (§4). Unconfirmed Company, "Not sure" or an outdated Case confirmation → **block** (paused until confirmed). A different jurisdiction, or a confirmed but unsupported Company jurisdiction → **escalate**. Resolved, but no approved screening covers the jurisdiction (DIFC) → **escalate** | No Case confirmation yet → `unknown`: missing information, no hold | `test_intake.py::test_the_case_jurisdiction_resolves_only_against_the_company_confirmation`, `::test_an_unresolved_jurisdiction_holds_and_nothing_jurisdiction_specific_runs`, `::test_a_difc_case_gets_no_uae_federal_rule_and_is_held_for_specialist_review`; `test_intake_api.py::test_an_unresolved_case_jurisdiction_holds_the_intake`, `::test_a_difc_case_gets_no_uae_federal_guidance_and_is_held`; e2e INTAKE-2, INTAKE-12, INTAKE-13 |
| `POLICY-ACK-CASE` | CL R5 | UAE-FED | step_caution → warn | **needs_legal_review** / active | Fires when the employee had not been told what was expected (`context.policy_awareness = no`) | "Not sure" or unanswered → `unknown`: no caution; listed as uncertain or missing | `test_intake.py::test_step_cautions_fire_only_on_the_answer_that_triggers_them`; `test_intake_api.py::test_cautions_follow_the_answers_and_can_be_corrected` |
| `UAE-ONE-PENALTY-SAME-INCIDENT` | CL R14 | UAE-FED | step_caution → warn | confirmed / active | Fires when the employer reports that a sanction was already issued for this same incident (`history.same_incident_sanction = yes`) | as above | same tests as above |
| `UAE-OFFDUTY-CONNECTION` | CL R15 | UAE-FED | step_caution → warn | confirmed / active | Fires when the incident happened outside work and no connection to work is stated (`context.location = outside_work` AND `context.work_connection ∈ {no, not_sure}`) | Location unanswered or "Not sure", or the connection unanswered → `unknown` | `test_intake.py::test_off_duty_conduct_without_a_stated_work_connection_is_cautioned`; e2e INTAKE-3 |
| `UAE-STOP-CALL-FIRST` | CL R16; "Structural Findings" R11 (ordering); IR §18 (no staffed expert workflow) | UAE-FED | blocking → escalate | **needs_legal_review** / active | Any of the nine factors answered Yes → **escalate**: the Case is held for specialist review (provisional) | Any factor unanswered or "Not sure" (and none Yes) → `unknown`: screening **not cleared**; the gate stays closed | `test_intake.py::test_any_one_high_risk_factor_holds_the_case`, `::test_screening_clears_only_when_every_factor_is_answered_no`; `test_intake_api.py::test_a_high_risk_answer_holds_the_case_and_creates_no_ticket`, `::test_an_uncertain_screening_answer_never_clears_the_screening`; tenant isolation `test_a_high_risk_hold_on_postgresql_writes_only_its_own_trace`; e2e INTAKE-5, INTAKE-10 |

Cross-cutting tests: predicate logic and "unknown is never No"
(`test_intake.py::test_an_answer_predicate_never_reads_unknown_as_no`,
`::test_combinations_use_kleene_logic`); source metadata and digest
(`::test_the_mapped_conditions_keep_their_source_metadata`,
`::test_the_rule_set_pins_its_sources_and_digest`); `not_enforced` never applies
(`::test_a_not_enforced_condition_is_never_applied`); review status never
authorizes an outcome (`::test_conditions_under_legal_review_never_authorize_an_outcome`).

### Interpretations made (for JJ's review)

These are engineering readings of the sources, chosen to be the more
restrictive where the sources leave room:

1. **Routing actions.** The workbook action cell for the routing rule says
   "blocking", which is not one of the Legend's actions. Its guidance says "ask
   the customer to confirm, or escalate": unclear → block (ask), conflicting or
   unsupported → escalate.
2. **DIFC.** Nothing approved screens a DIFC Case (the screening condition is
   UAE-FED; "proposed SHARED" isn't approved). A resolved DIFC Case is held for
   specialist review rather than screened with a Federal rule or left
   unscreened (Structural Findings R25 "fail safe"; IR §4, §17).
3. **Off-duty connection.** The trigger reads "no *stated* connection", so
   "Not sure" counts with "No"; an unanswered connection is unknown.
4. **One penalty per incident.** The workbook ties this to an issue thread that
   doesn't exist (analysis C9). M2-02 asks the employer for the fact and shows
   the caution at intake, because any action from the Case would be a second
   sanction for the same incident.
5. **Holds and cautions.** While a Case is held for specialist review, no
   caution is shown (no self-service guidance); cautions are still evaluated
   and recorded.
6. **Correcting a screening answer** lifts the hold. The history keeps the hold
   and the change. Whether a high-risk hold should instead only be released by
   a specialist is a JJ decision (§8).

## 4. Jurisdiction routing

The Company Blueprint holds one operator-confirmed `employment_jurisdiction`
and its readiness (`app/companies/jurisdiction.py`). It has **no list of
operating jurisdictions** (the workbook's `operating_jurisdictions`), so it
can't say whether a Company is single-jurisdiction. That is the documented gap
(analysis C25). The minimal design compatible with the existing architecture,
with no second jurisdiction system:

- The Case question `jurisdiction.case_confirmation` is asked only when the
  Company's jurisdiction is confirmed and supported. Its options are built by
  the server from that confirmation: "Yes, ⟨Company jurisdiction⟩", "No, a
  different jurisdiction applies", "Not sure". A Case can never pick a
  jurisdiction the Company's confirmation doesn't support (422).
- The stored answer is the jurisdiction code it confirmed. If the operator
  later confirms a different jurisdiction, the old answer no longer matches,
  and the Case is paused until it's confirmed again.
- The basis is recorded on every save: the routing result's inputs hold the
  Company readiness, reason and jurisdiction and the Case answer.
- Unconfirmed, unclear, conflicting or unsupported → no jurisdiction-dependent
  step (the safety screening) can be answered (409), and no jurisdiction-
  specific condition runs.
- UAE Federal and DIFC content stay apart: only the resolved tag's conditions
  run, and no Federal statutory wording reaches a DIFC Case (checked in API
  tests and e2e INTAKE-12).
- No production jurisdiction setting and no onboarding scope changed.

## 5. Safety screening, holds and the gate

- Nine factors, each Yes / No / Not sure. HeroOS stores only the enumerated
  answer; the step asks for no details. Each factor is a separate question so
  the hold can say what caused it and an uncertain answer can't clear anything.
- **Positive** (any Yes) → hold `specialist_review` (escalate, provisional).
  The hold names the factors in plain words, says a Yes isn't a finding about
  the employee, and says HeroOS doesn't offer expert review in the app yet and
  hasn't contacted anyone (IR §18). **No ticket is created**: there is no
  ticket table, and a held save writes only the submission, its facts and its
  evaluation (proven on PostgreSQL).
- **Not cleared** (a Not sure, no Yes) → status `screening_not_cleared`; the
  gate stays closed.
- Answers stay saveable while held: the employer can correct them; the gate
  stays closed while any hold is in force.
- The screening precedes any future informal-resolution or disciplinary-action
  option: those stages must check `next_stage_open`, which is true only for
  `intake_recorded`.

Statuses, highest first: `held_for_specialist_review` → `awaiting_jurisdiction`
→ `case_created` (nothing answered) → `intake_in_progress` →
`screening_not_cleared` → `intake_recorded`.

## 6. Persistence (migration D2, `e64497d997d8`)

- **`workflow_evaluations`** (append-only): one row per saved submission,
  written in the same transaction and under the same instance lock (the M2-01
  lock and revision checks are unchanged). It holds the status, hold and
  reason, resolved jurisdiction, screening state, every condition's result with
  the enumerated answers it read (never free text), and the definition
  version, rule-set version and digest. Company-qualified foreign key to the
  submission, RLS `tenant_isolation`, runtime SELECT/INSERT only, nothing for
  the operator, `heroos_schema_contract()` = 5. Downgrade refuses once a row
  exists.
- The Case jurisdiction confirmation is a `case_facts` answer. There is no
  mutable status column: the current state is recomputed on every read (the
  Company's readiness can change at any time). The rows are the trace of what
  each save produced.
- **Case history** is composed from append-only rows only: the instance
  (created), the submissions (which answers changed: labels, never values) and
  the differences between consecutive evaluations (jurisdiction confirmed,
  hold placed or lifted and why, screening result, cautions raised or no longer
  applying, intake recorded). Saves made before D2 have no evaluation; their
  history shows the saves only.
- **Definition v2** keeps v1's initial-facts step unchanged and declares v1
  Cases compatible, so M2-01 Cases continue into the intake. A Case keeps the
  version it started with; each evaluation records the version used.
- **Deployment order:** D2, then the API and the operator CLI (both require
  contract 5), then the web app. The M2-01 API keeps working on D2 (rehearsed:
  e2e MIG-37 to MIG-41). After any v2 Case exists, an API rollback to M2-01
  can't read it: roll forward.

## 7. Privacy and safety boundaries

- Synthetic data only, in tests, fixtures and demos.
- The screening stores Yes / No / Not sure answers about pregnancy or
  maternity leave, sick leave and a medical condition: health-related
  information about an identifiable employee. It is stored only as the
  enumerated answer, shown only to Company administrators, never logged
  (API logs carry the hold kind only), and never copied into evaluation text.
  Production use needs JJ's privacy approval (§8).
- No deletion, retention expiry, deadlines or reminders (PRIV-001 to PRIV-005,
  PRIV-020 pending).
- No AI, no external service, no document generation.

## 8. Open decisions for JJ

1. Legal review of `POLICY-ACK-CASE` and `UAE-STOP-CALL-FIRST`
   (`needs_legal_review`). They are shown as provisional.
2. The definitions of "recently complained" and "senior employee".
3. Whether the screening (and the other "proposed SHARED" conditions) may
   apply to DIFC Cases; until then DIFC Cases are held.
4. Whether a high-risk hold can be lifted by correcting an answer, or only by
   a specialist once an expert workflow exists.
5. Federal no-notice dismissal: the screening factor "dismissal without notice
   is being considered" always escalates (analysis C7).
6. Multi-jurisdiction Companies: a Blueprint list of operating jurisdictions,
   and who confirms the Case jurisdiction (analysis C25).
7. Privacy approval for storing the health-related screening answers, and the
   retention decisions PRIV-001 to PRIV-005.
8. Approved customer wording for the cautions and holds (currently neutral
   engineering wording based on the approved rules).
