# HeroOS V1 Privacy & Security Decision Register

**Status:** Authoritative engineering decision record (normalized in M1-08)  
**Owner:** Technical Lead  
**Business Decision Owner:** JJ  
**Milestone:** M1 — Foundation & Security  
**Issues:** M1-01 (created), M1-07 (PRIV-016 to PRIV-019 added), M1-08 (normalized)  
**Last updated:** 2026-10-08  
**Related:** [Third-Party Service Inventory](third-party-service-inventory.md),
[Production Security Gates](../architecture/production-security-gates.md)

## Purpose

This register tracks material privacy, retention and data-governance decisions
that must not be silently encoded by engineering.

For each decision, engineering should present:

1. available technical options
2. privacy implications
3. EU/GDPR-standard considerations
4. UAE considerations where relevant
5. cost implications
6. technical recommendation
7. legal-review requirement
8. JJ decision

Engineering recommendations are technical recommendations and do not replace
legal advice.

This file is the **single authoritative register**. Architecture documents, the
service inventory and any review packet refer to decisions by ID. They must not
restate a decision outcome differently. If another document disagrees with this
register, this register is correct and the other document is fixed.

---

## 1. Ownership

| Role | Holder | Responsibility |
| --- | --- | --- |
| Decision owner | JJ | Approves, approves with conditions, rejects, defers or requests further analysis, one decision at a time |
| Technical owner | Technical Lead (Aries) | Technical facts, options, cost implications, engineering recommendation, register maintenance, implementation traceability |
| Legal/privacy reviewer | **Not yet assigned** | Answers the legal/privacy question stated in each packet. Until a reviewer is assigned, no decision can record legal/privacy confirmation |
| Implementers | Engineering | Implement only approved decisions and record implementation and verification evidence |

Every decision in this register has JJ as decision owner and the Technical Lead
as technical owner unless its packet states otherwise.

---

## 2. Decision Lifecycle

```text
Pending Analysis
      |
      v
Ready for JJ Review  <---------------------+
      |                                    |
      v                                    |
Legal Review Required  (when the packet    |
      |                 needs legal input) |
      v                                    |
Approved / Rejected / Deferred  -----------+  (re-review trigger or new version)
      |
      v
Implementation status: Implementation tracked -> Implemented -> Verified
```

Not every decision passes through every state. A decision may go straight from
`Pending Analysis` to `Legal Review Required` when legal input is the next
blocking step.

### Decision status values

| Status | Meaning | Evidence needed to enter it |
| --- | --- | --- |
| `Pending Analysis` | Engineering analysis or required information is incomplete | None |
| `Ready for JJ Review` | The packet is complete enough for JJ to decide or to give direction | Complete packet in this register |
| `Legal Review Required` | Legal/privacy input on the stated question is needed before JJ can finalize | The legal/privacy question is written in the packet |
| `Approved` | JJ approved an outcome | Decision evidence, date and version. Legal/privacy review `Confirmed` or `Not required` |
| `Rejected` | JJ rejected the proposal | Decision evidence, date and version |
| `Deferred` | JJ deliberately postponed the decision | Decision evidence, date and version, plus a re-review trigger |
| `Superseded` | Replaced by another decision ID | Pointer to the replacing ID. The record is kept |

Rules:

- An engineering recommendation is not approval.
- `Ready for JJ Review` is not approval.
- `Legal Review Required` is not legal approval.
- A decision stays pending until actual evidence says otherwise.
- `Approved` requires actual JJ/business approval evidence.
- Legal/privacy confirmation requires actual legal/privacy review evidence.
- Approval is never inferred from implementation, from an issue existing, from a
  recommendation being written or from a developer comment.
- Legal confirmation is never inferred from an engineering document.

---

## 3. Field Vocabularies

### Legal/privacy review

| Value | Meaning |
| --- | --- |
| `Required` | A specific legal/privacy question must be confirmed before the decision can be finalized |
| `Review Required` | Legal/privacy review must confirm whether any legal constraint applies. The decision is otherwise mainly operational or product |
| `Not required` | Recorded only with evidence that legal/privacy review was waived by JJ or the reviewer |
| `Confirmed` | The legal/privacy reviewer's written output is referenced in `Legal/privacy evidence` |

`Required` and `Review Required` are the values used since M1-01 and are
preserved.

### JJ decision

`Pending`, `Approved`, `Approved with conditions`, `Rejected`, `Deferred`,
`Further analysis requested`. Every value other than `Pending` needs
`Decision evidence`, `Decision date` and `Decision version`.

### Implementation impact

States whether the unresolved decision currently blocks engineering. One or
more of:

| Value | Meaning |
| --- | --- |
| `Not currently blocking` | Current engineering can continue |
| `Blocks M2 feature` | A named M2 feature must not be built until decided |
| `Blocks M3 production activation` | A named M3 configuration cannot be finalized |
| `Blocks external data processing` | No production customer data may reach the named external processor |
| `Blocks deletion implementation` | No automated or user-facing deletion, anonymization or purge for the named data may be built |

M1-08 itself does not depend on any decision being approved.

### Implementation status

| Value | Meaning |
| --- | --- |
| `Not started` | No implementation work exists |
| `Technical foundation complete` | Technical primitives the decision will rely on exist. The **policy** is not implemented |
| `Blocked pending decision` | The next implementation step cannot proceed without this decision |
| `Implementation tracked` | Decision approved and implementation work is linked |
| `Implemented` | Approved policy implemented. Requires PR/commit evidence |
| `Verified` | Implementation verified. Requires test, drill or configuration evidence |

A technical primitive never makes a policy `Implemented`. For example, M1-07
backup tooling does not implement a backup retention policy.

---

## 4. Evidence Rules

- **JJ decision evidence** is a dated written record (for example a Linear
  comment, email or meeting minutes) referenced by location in
  `Decision evidence`. Engineering records the decision as written and does not
  extend it.
- **Legal/privacy evidence** is the reviewer's written output, referenced in
  `Legal/privacy evidence`.
- **Implementation evidence** is a PR or commit. **Verification evidence** is a
  test, restore drill, configuration export or equivalent.
- Missing values are written as `—` or `Pending`. Fields are never filled with
  invented values.
- Statements of law are written only when approved legal material in this
  repository supports them. Otherwise the packet says: *Not established in
  engineering documentation; legal/privacy confirmation required.*

---

## 5. Versioning and Change History

- `Decision version` is `—` until JJ records a first decision, which is `v1`.
  Each later change to the decided outcome is `v2`, `v3`, and so on.
- Packet edits before a decision (analysis, options, status moves before a JJ
  decision) are `Packet revision` rows in the packet history. They do not change
  the version.
- An approved decision is **never edited in place**. To change it:
  1. keep the existing `Decision vN` block and mark it `Superseded by vN+1`;
  2. add a `Decision vN+1` block with the new outcome;
  3. add a history row with the date, previous decision, new decision, reason,
     approving authority and affected implementation;
  4. update `Decision version`, `Decision date`, `Decision evidence` and the
     traceability matrix.
- Decision IDs are never renumbered, deleted or reused. A decision replaced by
  another ID is marked `Superseded` with a pointer to the new ID.
- Register-level changes are listed in the [Change Log](#change-log).

### How JJ records a decision on one item

Only the affected packet, its summary-table row and its traceability row change:

1. JJ states the outcome for one decision ID in writing.
2. Engineering updates that packet: `JJ decision`, `Decision evidence`,
   `Decision date`, `Decision version`, `Status`, and adds a `Decision vN` block
   and a history row.
3. Engineering updates the same row in the summary table and the traceability
   matrix.

No other decision changes. A JJ decision on one ID never implies a decision on a
related ID.

---

## 6. M1-08 Audit Findings

Audit of the register as it stood on `main` at `5551675` (after M1-07).

- IDs found: PRIV-001 to PRIV-019. All unique and contiguous. No gaps, no
  duplicates.
- Every decision was `Pending Analysis` with `JJ Decision: Pending`. No JJ
  approval or legal confirmation existed anywhere in the repository or in
  commit history. Nothing was conflicting.
- Legal review values were `Required` or `Review Required`, used without a
  definition. Both are preserved and now defined (§3).
- No decision had an owner field per decision, a date, a version,
  implementation status, implementation impact or re-review trigger.
- New M1 evidence: M1-04 schema foreign-key behavior and Company-scoped
  repository delete functions (PRIV-002, PRIV-003, PRIV-008), M1-07 storage,
  logging and backup foundations (see Appendix A).

### Overlaps (documented; no record deleted or merged)

| IDs | Relationship | Handling |
| --- | --- | --- |
| PRIV-007 / PRIV-017 / PRIV-018 | Backup retention, recovery objectives and deleted data in backups are coupled. The PITR window bounds the achievable recovery point | Separate decisions with cross-references |
| PRIV-004 / PRIV-019 | Document retention (how long) vs. object versioning (whether deleted objects remain recoverable for a window) | Separate. PRIV-019 must be consistent with PRIV-004 and PRIV-018 |
| PRIV-012 / PRIV-013 | AI cross-border processing vs. general residency | AI cross-border is decided only in PRIV-012. PRIV-013 covers everything else |
| PRIV-009 / PRIV-014 | Selecting an AI provider is one instance of the processor approval process | PRIV-009 follows the PRIV-014 process |
| PRIV-010 / PRIV-001 / PRIV-004 | AI outputs saved into a Case or document become Case/document data | PRIV-010 covers provider-side retention and raw prompt/response storage only |
| PRIV-016 / all retention and deletion decisions | Legal hold suspends deletion | PRIV-016 is referenced by each deletion-related packet |
| PRIV-008 | "Account" is ambiguous (customer Company or individual User account) | Interpreted as covering both. Scope confirmation requested from JJ. No new ID |

---

## Decision Register

| ID | Decision | Status | Technical Recommendation | JJ Decision | Legal Review |
|---|---|---|---|---|---|
| PRIV-001 | Active and closed Case data retention | Legal Review Required | Define retention based on product need, legal obligations and storage limitation rather than an arbitrary universal duration | Pending | Required |
| PRIV-002 | Closed-case deletion vs anonymization vs continued retention | Legal Review Required | Support explicit lifecycle behavior rather than universal soft deletion | Pending | Required |
| PRIV-003 | Employee / Case Subject data retention | Legal Review Required | Align retention with active case/company need and applicable legal requirements | Pending | Required |
| PRIV-004 | Uploaded and generated document retention | Legal Review Required | Keep document lifecycle configurable and tied to approved policy | Pending | Required |
| PRIV-005 | Audit-event retention | Legal Review Required | Preserve sufficient audit history while minimizing unnecessary sensitive content | Pending | Review Required |
| PRIV-006 | Application-log retention | Pending Analysis | Use minimized operational logs and shorter retention than business records unless operational need requires otherwise | Pending | Review Required |
| PRIV-007 | Database-backup retention | Pending Analysis | Balance recoverability with storage limitation and approved operational need | Pending | Review Required |
| PRIV-008 | Account / Company deletion behavior | Legal Review Required | Define controlled deletion/anonymization workflow rather than immediate unrestricted cascade deletion | Pending | Required |
| PRIV-009 | Production AI provider and model | Pending Analysis | Select only after capability, privacy, residency and cost comparison | Pending | Required |
| PRIV-010 | AI input/output retention | Pending Analysis | Prefer provider configuration minimizing or disabling provider retention where commercially/technically feasible | Pending | Required |
| PRIV-011 | AI provider training/data-use policy | Pending Analysis | Production customer data should not be used for general provider model training without explicit approved basis | Pending | Required |
| PRIV-012 | AI processing location / cross-border transfer | Pending Analysis | Evaluate actual provider processing location rather than assuming UAE hosting keeps AI processing in UAE | Pending | Required |
| PRIV-013 | Production data residency model | Pending Analysis | Keep primary HeroOS application/database/document infrastructure in AWS UAE; separately review every external processor | Pending | Required |
| PRIV-014 | Production subprocessor/vendor approval process | Pending Analysis | Maintain service inventory and review material data-processing changes before activation | Pending | Required |
| PRIV-015 | Transactional email content and retention | Pending Analysis | Minimize HR-sensitive content in email; prefer secure in-product access for sensitive case details | Pending | Review Required |
| PRIV-016 | Legal hold requirements | Legal Review Required | Define whether and when a legal hold suspends deletion of Cases, documents/objects, logs and backups before any automated deletion is implemented | Pending | Required |
| PRIV-017 | Recovery point objective (RPO) and recovery time objective (RTO) | Pending Analysis | Approve explicit RPO/RTO targets before M3 configures RDS backups/PITR and restore drills; engineering will present the cost of each option | Pending | Review Required |
| PRIV-018 | Deletion requests vs. existing backups, and treatment of restored backups | Legal Review Required | Decide whether deleted data may persist in backups until they expire, how such backups are protected meanwhile, and how deletions are re-applied after any restore | Pending | Required |
| PRIV-019 | Private object versioning and deleted-object recoverability | Ready for JJ Review | Decide whether S3 versioning / a recovery window applies to private objects, consistent with PRIV-004 and PRIV-018 | Pending | Review Required |
| PRIV-020 | Deletion mechanics and interim deletion behavior | Ready for JJ Review | No user-facing deletion in M2 until the retention decisions are approved; no universal soft delete | Pending | Review Required |

---

## Decision Packets

Each packet uses the same fields. Analysis sections are engineering analysis,
not legal advice. "EU/GDPR-standard considerations" are privacy
considerations, not legal determinations. Values not yet known are `—` or
`Pending`.

### PRIV-001 — Active and closed Case data retention

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (Case retention and expiry) |
| Implementation status | Not started |
| Related decisions | PRIV-002, PRIV-003, PRIV-004, PRIV-005, PRIV-016, PRIV-018, PRIV-020 |
| First recorded | M1-01 |

**Question.** How long are active and closed Case records kept, and which event
starts the retention period?

**Technical facts.** The M1 `cases` table holds `company_id`, an optional
`subject_id`, `case_type`, `title` and timestamps. There is no closure state,
closure timestamp or retention metadata, and no automated deletion. Workflow
instances, facts, decisions and documents attached to Cases are M2.

**Options.**

- A. A defined retention period per Case category, counted from Case closure,
  then deletion or anonymization (PRIV-002).
- B. Retention configurable per Company within approved bounds.
- C. Retain until the customer deletes the Case or offboards (PRIV-008).
- D. Indefinite retention.

**Privacy implications.** Cases hold HR-sensitive narratives and facts about
identifiable employees. Longer retention increases breach exposure and the
volume of data subject to access and deletion requests. Shorter retention
reduces the history available for investigations, disputes and customer
reference.

**EU/GDPR-standard considerations.** Storage-limitation and purpose-limitation
considerations: retention should be justified by purpose and documented.
Applicable periods are not established in engineering documentation;
legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** Relational storage cost for Case data is
small. The material cost is engineering: lifecycle states, scheduled expiry,
anonymization, legal-hold exceptions (PRIV-016) and verification. Option B adds
per-Company configuration and support effort. Option D has the lowest
engineering cost and the highest privacy exposure.

**Engineering recommendation.** Original (M1-01): *Define retention based on
product need, legal obligations and storage limitation rather than an
arbitrary universal duration.* M1-08: count retention from an explicit Case
closure event that M2 records, so any approved policy can be applied without a
data migration. Choose between A and B after legal input. Avoid D.

**Legal/privacy question.** Which retention periods or criteria apply to HR
advisory case records for UAE Federal / MOHRE and DIFC customers, and are there
minimum periods (for example for employment disputes) or maximum periods?

**Information required before decision.** The legal/privacy answer above. JJ
product input on whether customers may configure retention (Option B).

**Implementation traceability.** M2 Case lifecycle (closure event and
timestamps): not started. Case retention/expiry job: blocked pending decision.

**Re-review trigger.** Legal input received; new jurisdiction added; new Case
categories.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; status to `Legal Review Required` | Technical Lead |

### PRIV-002 — Closed-case deletion vs anonymization vs continued retention

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (end-of-retention handling for Cases) |
| Implementation status | Not started |
| Related decisions | PRIV-001, PRIV-005, PRIV-016, PRIV-018, PRIV-020 |
| First recorded | M1-01 |

**Question.** When a Case reaches the end of its retention period (PRIV-001), is
it hard-deleted, anonymized or kept in a restricted archive?

**Technical facts.** M1 has a Company-scoped `delete_case` repository function
that hard-deletes a Case row. It is used by tests. No route exposes it. M2 adds
workflow instances, facts, decisions, documents and audit events that reference
Cases. See PRIV-020 for the mechanism and interim behavior.

**Options.**

- A. Hard delete the Case, its dependent records and its objects.
- B. Anonymize: remove or replace identifying fields and free text, keep
  structural data (Case type, dates, outcomes).
- C. Restricted archive: keep the Case, hidden from normal use, with limited
  access.
- D. Soft delete: flag the Case as deleted and hide it; the data stays.

**Privacy implications.** A removes the data (subject to backups, PRIV-018). B
depends on the anonymization actually being effective; HR free text and
narratives are hard to anonymize reliably. C and D keep the full personal data.
D also makes data look deleted to users while it is still stored.

**EU/GDPR-standard considerations.** Storage-limitation consideration. Whether
a given anonymization approach is sufficient for data to stop being personal
data is a legal/privacy question that engineering cannot confirm.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** A needs a defined cascade across M2
entities and S3 objects. B has the highest engineering cost: field-level rules
per entity, free-text handling and verification. C and D are cheap to build but
carry ongoing storage, access-control and exposure cost, and D adds a deleted
filter to every query.

**Engineering recommendation.** Original (M1-01): *Support explicit lifecycle
behavior rather than universal soft deletion.* M1-08: design M2 entities so
both A and B remain possible (explicit lifecycle states, a known map of
dependent records and objects). Do not adopt D as a universal mechanism
(PRIV-020). Choose after legal input.

**Legal/privacy question.** After the retention period, is deletion,
anonymization or restricted retention appropriate for closed HR cases, and what
anonymization standard, if any, would be acceptable?

**Information required before decision.** The legal/privacy answer above;
PRIV-001.

**Implementation traceability.** M2 Case lifecycle and dependent-record map:
not started. End-of-retention job: blocked pending decision.

**Re-review trigger.** Legal input received; PRIV-001 decided.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; status to `Legal Review Required` | Technical Lead |

### PRIV-003 — Employee / Case Subject data retention

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (Case Subject retention and deletion) |
| Implementation status | Not started |
| Related decisions | PRIV-001, PRIV-002, PRIV-008, PRIV-016, PRIV-020 |
| First recorded | M1-01 |

**Question.** How long is data about an employee / Case Subject kept, including
after their Cases close or they leave the customer company, what happens to it
afterwards, and how are individual deletion requests handled?

**Technical facts.** `case_subjects` holds `company_id`, `subject_type`,
`display_name`, an optional `reference` and timestamps. Deleting a subject sets
`cases.subject_id` to NULL through the composite foreign key
(`ON DELETE SET NULL (subject_id)`), so the Case row survives without the link.
This is referential integrity, not an approved deletion policy. A
Company-scoped `delete_case_subject` repository function exists. No route
exposes it. Case free text may still identify the person after the subject row
is deleted.

**Options.**

- A. Keep subject data while any related Case is retained, then delete or
  anonymize it with the last Case.
- B. An independent retention period from the subject's last activity.
- C. Customer-initiated deletion at any time, subject to legal hold (PRIV-016).
- D. A combination of A and C.

**Privacy implications.** Case Subjects are identifiable employees of customer
companies, who are not HeroOS users. Deleting the subject row alone does not
remove identifying content from Cases or documents.

**EU/GDPR-standard considerations.** Storage-limitation consideration, and
handling of requests from individuals to access or delete their data. Who
receives and decides such requests (HeroOS or the customer company) depends on
HeroOS's legal role, which is not established in engineering documentation
(see PRIV-014). Legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** A is the simplest consistent model. C
needs UI, audit, propagation to Case content and documents, and legal-hold
checks.

**Engineering recommendation.** Original (M1-01): *Align retention with active
case/company need and applicable legal requirements.* M1-08: A as the default
model, with C added only if legal review supports it, so subject data does not
outlive the Cases that justify it. How subject deletion propagates into Case
content is decided with PRIV-002 and PRIV-020.

**Legal/privacy question.** What retention applies to employee data held in HR
advisory cases, what changes when the employee leaves, and who handles deletion
requests from customer companies' employees?

**Information required before decision.** The legal/privacy answer above;
HeroOS role classification (PRIV-014).

**Implementation traceability.** M2 subject lifecycle: not started. Subject
deletion/anonymization: blocked pending decision.

**Re-review trigger.** Legal input received; PRIV-001 or PRIV-002 decided.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; status to `Legal Review Required` | Technical Lead |

### PRIV-004 — Uploaded and generated document retention

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (document deletion, S3 lifecycle expiry) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-001, PRIV-016, PRIV-018, PRIV-019 |
| First recorded | M1-01 |

**Question.** How long are uploaded and generated documents (private objects)
kept, and are they deleted with their Case or on their own schedule?

**Technical facts.** M1-07 storage primitive: write-once objects under
`companies/<company uuid>/<object uuid>`, Company-authorized access, and
immediate hard delete. No document metadata exists yet (M2 Document domain).
Production S3 is not active, and versioning and lifecycle rules are not
configured (PRIV-019). See Appendix A.

**Options.**

- A. Documents follow their Case's retention (PRIV-001).
- B. Retention periods per document type.
- C. Customer-managed deletion, subject to legal hold.
- D. For generated documents, store only the inputs and regenerate on demand.

**Privacy implications.** Documents may contain the most sensitive content in
HeroOS (ADR-005). Documents and their Case expiring separately can leave
orphaned documents or Cases that refer to missing documents.

**EU/GDPR-standard considerations.** Storage-limitation consideration. Periods
not established in engineering documentation; legal/privacy confirmation
required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability, including any document-type-specific obligations.

**Cost / operational implications.** S3 storage cost grows with volume and
retention length. Lifecycle rules are cheap to run. Per-type rules (B) add
engineering and support effort. Versioning (PRIV-019) adds storage for
non-current versions. D reduces stored documents but needs reproducible
generation.

**Engineering recommendation.** Original (M1-01): *Keep document lifecycle
configurable and tied to approved policy.* M1-08: A as the baseline. M2
document metadata should carry Company, Case, document type and timestamps so
any approved rule can be applied. No S3 lifecycle expiry until approved.

**Legal/privacy question.** Are there retention obligations specific to
particular employment document types for UAE Federal / MOHRE or DIFC
customers?

**Information required before decision.** The legal/privacy answer above;
PRIV-001.

**Implementation traceability.** M1-07 private object storage: technical
foundation complete. M2 Document metadata: not started. M3 S3 lifecycle rules:
blocked pending decision.

**Re-review trigger.** Legal input received; PRIV-001 decided; new document
types.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized with M1-07 evidence; status to `Legal Review Required` | Technical Lead |

### PRIV-005 — Audit-event retention

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (audit-event purge) |
| Implementation status | Not started |
| Related decisions | PRIV-002, PRIV-008, PRIV-016, PRIV-020 |
| First recorded | M1-01 |

**Question.** How long are audit events kept, may they outlive the Case or User
they describe, and what content may they contain?

**Technical facts.** Audit events are planned M2 tenant-private entities
(ADR-004, [Tenant Isolation §9](../architecture/tenant-isolation.md)). None
exist in M1. Application logs (PRIV-006) are not audit events.

**Options.**

- A. Same retention as the related Case.
- B. Longer than the Case, with minimized content (actor, action, target IDs,
  time) once the Case is deleted or anonymized.
- C. A fixed period independent of the Case.

**Privacy implications.** Audit events identify the acting Users and reference
Case Subjects. Keeping them after Case deletion preserves accountability but
keeps personal data. Minimized content reduces exposure.

**EU/GDPR-standard considerations.** Data-minimization and storage-limitation
considerations. Periods not established in engineering documentation;
legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** Storage is small. Engineering cost is in
minimization and in keeping audit records independent of Case deletion.

**Engineering recommendation.** Original (M1-01): *Preserve sufficient audit
history while minimizing unnecessary sensitive content.* M1-08: M2 audit events
record actor, action, target identifiers and time, not HR narrative content, so
any approved retention can be applied without exposing Case content. Audit
events should not be removed implicitly by database cascades (PRIV-020).

**Legal/privacy question.** Are there minimum or maximum periods for audit
records of HR advisory actions, and may minimized audit records outlive deleted
Case data?

**Information required before decision.** The legal/privacy answer above.

**Implementation traceability.** M2 audit events: not started. Audit purge:
blocked pending decision.

**Re-review trigger.** Legal input received; M2 audit-event design review.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; status to `Legal Review Required` | Technical Lead |

### PRIV-006 — Application-log retention

| Field | Value |
| --- | --- |
| Status | Pending Analysis |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks M3 production activation (CloudWatch log-group retention) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-008, PRIV-013, PRIV-014 |
| First recorded | M1-01 |

**Question.** How long are application logs kept in CloudWatch (and any
archive)?

**Technical facts.** See Appendix A and
[Observability](../architecture/observability.md). Logs hold opaque,
pseudonymous User and Company identifiers and no HR content. The M3 gate
([Production Security Gates §6](../architecture/production-security-gates.md))
requires an explicitly configured retention, never the "never expire" default.
No log group exists.

**Options.**

- A. A short operational window.
- B. A longer window that supports security-incident investigation.
- C. Tiered: short in CloudWatch, longer in an access-controlled archive.

No value is proposed in M1-08.

**Privacy implications.** Lower sensitivity than business records. Longer
retention keeps more pseudonymous activity history per User and Company.

**EU/GDPR-standard considerations.** Data-minimization and storage-limitation
considerations. Not established in engineering documentation; legal/privacy
confirmation required.

**UAE considerations.** Legal/privacy review required for UAE/DIFC
applicability.

**Cost / operational implications.** CloudWatch Logs charges for ingestion and
storage, so retention length drives cost. C adds an archive pipeline and its
access control.

**Engineering recommendation.** Original (M1-01): *Use minimized operational
logs and shorter retention than business records unless operational need
requires otherwise.* M1-08: A or B, with an explicit value per log group
proposed at M3 planning together with a cost estimate. Keep logs free of HR
content (enforced by M1-07 tests).

**Legal/privacy question.** Do minimum or maximum periods apply to operational
logs that contain pseudonymous user identifiers?

**Information required before decision.** Candidate retention values with
CloudWatch cost estimates (engineering, M3 planning). Incident-investigation
needs (Technical Lead and JJ).

**Implementation traceability.** M1-07 privacy-safe logging: technical
foundation complete. M3 CloudWatch log groups and retention: blocked pending
decision.

**Re-review trigger.** A third-party log or error service is proposed; log
content changes; security incident review.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized with M1-07 evidence; remains `Pending Analysis` | Technical Lead |

### PRIV-007 — Database-backup retention

| Field | Value |
| --- | --- |
| Status | Pending Analysis |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks M3 production activation (RDS automated-backup retention, snapshot policy) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-013, PRIV-016, PRIV-017, PRIV-018 |
| First recorded | M1-01 |

**Question.** How long are production database backups kept, and which backup
types are used?

**Technical facts.** See Appendix A and
[Backup and Recovery §7](../architecture/backup-and-recovery.md). The logical
backup/restore procedure is verified on disposable databases locally and in CI.
No production backup exists. At M3: RDS automated backups with PITR, encrypted
with KMS. Production logical dumps, if used, only in an encrypted,
access-controlled store with an approved retention. Cross-region copies only if
approved (PRIV-013).

**Options.**

- A. RDS automated backups/PITR only, with a retention window to approve.
- B. A plus manual snapshots kept for a defined period.
- C. A plus periodic logical dumps in an encrypted store.

**Privacy implications.** Backups are full copies of production HR data,
including data deleted since they were taken. A longer window keeps deleted data
recoverable for longer (PRIV-018).

**EU/GDPR-standard considerations.** Storage-limitation consideration for data
kept only in backups. Not established in engineering documentation;
legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE/DIFC
applicability, and PRIV-013 for any backup copy outside `me-central-1`.

**Cost / operational implications.** Backup storage grows with database size
and window length. Manual snapshots persist until someone deletes them, which
is ongoing cost and exposure.

**Engineering recommendation.** Original (M1-01): *Balance recoverability with
storage limitation and approved operational need.* M1-08: A as the baseline,
sized together with PRIV-017 and PRIV-018. B or C only for a stated recovery
need. No manual snapshot without a named owner and expiry.

**Legal/privacy question.** Does keeping deleted personal data in backups until
they expire need specific justification or disclosure to customers?

**Information required before decision.** PRIV-017 targets. Database size
projection and cost estimate (engineering, M3 planning).

**Implementation traceability.** M1-07 logical backup/restore: technical
foundation complete (`make backup-restore-check`). M3 RDS backup configuration:
blocked pending decision.

**Re-review trigger.** PRIV-017 decided; database growth; restore-drill
findings.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized with M1-07 evidence; remains `Pending Analysis` | Technical Lead |

### PRIV-008 — Account / Company deletion behavior

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (Company offboarding, User account deletion) |
| Implementation status | Not started |
| Related decisions | PRIV-003, PRIV-004, PRIV-005, PRIV-006, PRIV-016, PRIV-018, PRIV-020 |
| First recorded | M1-01 |

**Scope.** "Account" is read as both the customer Company and an individual
User account. JJ is asked to confirm this scope.

**Question.** What happens to a Company's data when the customer leaves, and
what happens when an individual User account is removed?

**Technical facts.** No Company or User deletion workflow exists. Database
foreign keys cascade from `companies` to memberships, Company Blueprints, Case
Subjects and Cases, and from `users` to memberships. The `users` table holds
only an opaque `identity_subject` and timestamps; identity data such as email
lives in the identity provider (Cognito at M3). Objects under
`companies/<company uuid>/`, log entries and backups are not touched by a
database cascade. See Appendix A.

**Options (Company).**

- A. Immediate hard delete: database cascade plus object deletion.
- B. Staged offboarding: suspend access, export window, then delete or
  anonymize after a defined period, then confirm completion.
- C. Restricted archive for a defined period, then deletion.

**Options (User).** Remove the Membership only (the User row stays for audit
attribution); delete the User and the identity-provider account; or anonymize
the User.

**Privacy implications.** Company deletion removes all employee and Case data
of that customer, which is irreversible and interacts with legal hold
(PRIV-016) and backups (PRIV-018). User deletion interacts with audit
attribution (PRIV-005).

**EU/GDPR-standard considerations.** Storage-limitation consideration and
handling of deletion requests. The obligations depend on customer contract
terms and HeroOS's legal role, neither of which is documented in the
repository. Legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** B has the highest engineering cost
(offboarding states, export, scheduled deletion across database, S3 and
identity provider, verification). A is cheapest but irreversible and exposed to
mistakes.

**Engineering recommendation.** Original (M1-01): *Define controlled
deletion/anonymization workflow rather than immediate unrestricted cascade
deletion.* M1-08: B for Companies. For Users, remove the Membership to revoke
access and handle erasure of the User identity separately under legal
guidance. The database cascade is referential integrity, not the deletion
workflow; no product path may call it until this decision is approved
(PRIV-020).

**Legal/privacy question.** What must happen to a customer's data at contract
end (deletion, return, retention period), and how are User account erasure
requests handled?

**Information required before decision.** The legal/privacy answer above;
customer contract terms; JJ scope confirmation.

**Implementation traceability.** Company offboarding and User deletion: not
started; blocked pending decision.

**Re-review trigger.** Legal input received; customer contract template
available.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-07 | Recorded in M1-01, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; scope note added; status to `Legal Review Required` | Technical Lead |

### PRIV-016 — Legal hold requirements

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (every automated or user-facing deletion path) |
| Implementation status | Not started |
| Related decisions | PRIV-001, PRIV-002, PRIV-003, PRIV-004, PRIV-005, PRIV-006, PRIV-007, PRIV-008, PRIV-018, PRIV-019 |
| First recorded | M1-07 |

**Question.** Does HeroOS support legal holds; who may place and release one;
what it covers (Company, Case, Case Subject, document); and what it suspends
(Case and document deletion, object expiry, log expiry, backup expiry)?

**Technical facts.** No automated deletion exists, so nothing currently needs
suspending. S3 object lock is one possible storage mechanism (Appendix A).

**Options.**

- A. No legal-hold feature in V1. Deletion stays manual and case by case.
- B. An application-level hold on Company or Case, checked by every deletion
  path and audited.
- C. B plus storage-level object lock for held objects.

**Privacy implications.** A hold keeps data beyond its normal retention, so it
must be scoped, recorded and released. C can make objects undeletable, by
HeroOS too, until the lock ends.

**EU/GDPR-standard considerations.** A hold must be justified and limited to
what it needs to preserve. Not established in engineering documentation;
legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** B is moderate (a flag, checks in every
deletion path, audit). C adds object-lock configuration and the risk of
irreversible locks. A is cheapest but gives any later automated deletion no
safeguard.

**Engineering recommendation.** Original (M1-07): *Define whether and when a
legal hold suspends deletion of Cases, documents/objects, logs and backups
before any automated deletion is implemented.* M1-08: decide before any
automated deletion is built. Engineering leans to B. C only if legal review
identifies a need for storage-enforced immutability. Engineering will confirm
at M3 whether any chosen storage mechanism has to be configured when the
bucket is created.

**Legal/privacy question.** When must HeroOS or its customers preserve HR data
(litigation, investigations, regulator requests) for UAE Federal / MOHRE and
DIFC matters, and who may instruct a hold?

**Information required before decision.** The legal/privacy answer above.

**Implementation traceability.** Legal-hold flag and checks: not started;
required before the first deletion feature.

**Re-review trigger.** Legal input received; first automated deletion feature
proposed.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-08 | Recorded in M1-07, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; status to `Legal Review Required` | Technical Lead |

### PRIV-017 — Recovery point objective (RPO) and recovery time objective (RTO)

| Field | Value |
| --- | --- |
| Status | Pending Analysis |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks M3 production activation (RDS backup/PITR configuration, restore-drill acceptance criteria) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-007, PRIV-013, PRIV-018, PRIV-019 |
| First recorded | M1-07 |

**Question.** How much data loss (RPO) and how much downtime (RTO) is
acceptable for production, and who owns the recovery policy?

**Technical facts.** The logical backup/restore procedure and post-restore
security validation are verified on disposable databases locally and in CI. No
production backup exists. M3 plans RDS automated backups with PITR and
scheduled restore drills ([Backup and Recovery §7](../architecture/backup-and-recovery.md)).
Object recovery depends on PRIV-019. No restore duration has been measured in a
production-like environment.

**Options.**

- A. RDS automated backups/PITR in `me-central-1` only.
- B. A plus cross-region backup copies (better recovery from a regional failure;
  data leaves `me-central-1`, PRIV-013).
- C. A plus a Multi-AZ standby (shorter recovery from infrastructure failure;
  does not protect against logical corruption or bad deletes).
- D. Additional standby or replica infrastructure for tighter targets.

No RPO or RTO value is proposed in M1-08.

**Privacy implications.** B and D may copy production HR data outside
`me-central-1`. Longer PITR windows also lengthen how long deleted data remains
recoverable (PRIV-018).

**EU/GDPR-standard considerations.** Availability and resilience of personal
data are privacy and security considerations. No specific target is established
in engineering documentation.

**UAE considerations.** Legal/privacy review required for UAE/DIFC
applicability and for any cross-region copy (PRIV-013).

**Cost / operational implications.** Each step from A to D increases monthly
cost and operational complexity. Costed options will be prepared at M3
planning.

**Engineering recommendation.** Original (M1-07): *Approve explicit RPO/RTO
targets before M3 configures RDS backups/PITR and restore drills; engineering
will present the cost of each option.* M1-08: JJ states the business tolerance
for data loss and downtime. Engineering then presents costed options. Targets
are accepted only after a restore drill meets them. Recovery policy owner: JJ.
Recovery execution owner: Technical Lead.

**Legal/privacy question.** Do customer contracts or regulations impose
availability or recovery commitments?

**Information required before decision.** JJ business tolerance; cost
estimates (engineering, M3 planning); measured restore duration from the first
M3 restore drill.

**Implementation traceability.** M1-07 backup/restore verification: technical
foundation complete. M3 RDS backups/PITR and restore drills: blocked pending
decision.

**Re-review trigger.** First M3 restore drill; customer contract commitments;
material growth in data volume.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-08 | Recorded in M1-07, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; remains `Pending Analysis` | Technical Lead |

### PRIV-018 — Deletion requests vs. existing backups, and treatment of restored backups

| Field | Value |
| --- | --- |
| Status | Legal Review Required |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks deletion implementation (deletion ledger, restore reconciliation) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-004, PRIV-007, PRIV-008, PRIV-016, PRIV-017, PRIV-019, PRIV-020 |
| First recorded | M1-07 |

**Question.**

1. May deleted data remain in backups until those backups expire, and how are
   they protected meanwhile?
2. After a restore, how are deletions made since the backup re-applied, and who
   signs off before the restored database is put into service?
3. May production backups be restored outside production (for example into
   Staging)?

**Technical facts.** The recovery procedure stops at "re-apply deletions per
PRIV-018". Until this decision exists, a restored backup must not be put into
service without engineering and JJ sign-off
([Backup and Recovery §4](../architecture/backup-and-recovery.md)). No deletion
feature exists yet, so there is nothing to re-apply today. Production logical
dumps are never stored on developer machines (an existing engineering control).
Engineering does not consider editing individual records inside automated
backups practical.

**Options.**

- Q1: A. Backups expire on their normal schedule, encrypted and
  access-restricted meanwhile. B. Shorten backup retention to bound how long
  deleted data persists (PRIV-007).
- Q2: A. A deletion ledger that records identifiers (not content) of deleted
  records and objects and is re-applied after every restore. B. Manual
  reconciliation per restore.
- Q3: A. Production data restored only into production-protected
  environments. B. Restored copies anonymized before use outside production.
  C. Allowed with Staging access controls.

**Privacy implications.** Q1-A means "deleted" data persists in backups for the
backup window. Q2-A stores identifiers of deleted records, which are
pseudonymous data with their own retention. Q3-B and Q3-C copy production HR
data into weaker environments.

**EU/GDPR-standard considerations.** Whether retaining deleted data in backups
until expiry is acceptable, and how it is described to customers, is not
established in engineering documentation; legal/privacy confirmation required.

**UAE considerations.** Legal/privacy review required for UAE Federal / MOHRE
and DIFC applicability.

**Cost / operational implications.** Q2-A is moderate engineering work and must
exist before the first deletion feature. Q2-B is error-prone. Q3-B needs a
reliable anonymization pipeline.

**Engineering recommendation.** Original (M1-07): *Decide whether deleted data
may persist in backups until they expire, how such backups are protected
meanwhile, and how deletions are re-applied after any restore.* M1-08: Q1-A
with retention bounded by PRIV-007; Q2-A, built together with the first
deletion feature; sign-off by the Technical Lead and JJ before a restored
database goes into service; Q3-A.

**Legal/privacy question.** Is persistence of deleted data in encrypted backups
until expiry acceptable, how must it be described to customers, and is a
deletion ledger of identifiers acceptable?

**Information required before decision.** The legal/privacy answer above;
PRIV-007.

**Implementation traceability.** M1-07 restore procedure, post-restore
validation and sign-off gate: technical foundation complete. Deletion ledger and
restore reconciliation: blocked pending decision.

**Re-review trigger.** Legal input received; first deletion feature designed;
PRIV-007 decided.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-08 | Recorded in M1-07, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; restored-data question (Q3) made explicit; status to `Legal Review Required` | Technical Lead |

### PRIV-019 — Private object versioning and deleted-object recoverability

| Field | Value |
| --- | --- |
| Status | Ready for JJ Review |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks M3 production activation (S3 versioning and lifecycle configuration) |
| Implementation status | Technical foundation complete; Blocked pending decision |
| Related decisions | PRIV-004, PRIV-016, PRIV-017, PRIV-018 |
| First recorded | M1-07 |

**Question.** Should production private objects be recoverable for a window
after deletion (S3 versioning with expiry of non-current versions), or should
deletion be final?

**Technical facts.** Objects are write-once, so versioning would not protect
against overwrites (there are none); its benefit is recovering deleted objects.
Database backups do not include objects. If the database is restored to an
earlier point, its document references can point to objects deleted since, and
without versioning those objects are gone. See Appendix A.

**Options.**

- A. No versioning: deletion is immediate and irreversible.
- B. Versioning with a lifecycle rule that expires non-current versions after an
  approved window.
- C. Object lock for objects under legal hold (PRIV-016), alone or with B.

**Privacy implications.** B means deleted documents persist for the window,
which must be consistent with PRIV-018. A gives deletion finality. C prevents
deletion while active.

**EU/GDPR-standard considerations.** The recovery window is data kept after
deletion and should be justified and bounded. Not established in engineering
documentation; legal/privacy confirmation required for the window.

**UAE considerations.** Legal/privacy review required for UAE/DIFC
applicability.

**Cost / operational implications.** B stores non-current versions until they
expire, so the window length drives the extra cost; lifecycle rules are
required to bound it. A costs nothing extra. C adds lock-management effort and
irreversibility risk.

**Engineering recommendation.** M1-07: *Decide whether S3 versioning / a
recovery window applies to private objects, consistent with PRIV-004 and
PRIV-018.* M1-08: B, because accidental or malicious deletion of HR documents
cannot otherwise be recovered and a database restore could otherwise reference
missing documents. The window length is set with PRIV-004/PRIV-018 legal input
and kept consistent with the PITR window (PRIV-007). C only if PRIV-016
requires it.

**Legal/privacy question.** Is a bounded recovery window for deleted documents
acceptable, and how must it be described to customers?

**Information required before decision.** JJ direction (A, B or C) can be given
now. The window length needs PRIV-004/PRIV-018 legal input and an M3 cost
estimate.

**Implementation traceability.** M1-07 write-once storage and hard delete:
technical foundation complete. M3 S3 versioning and lifecycle: blocked pending
decision.

**Re-review trigger.** PRIV-004, PRIV-016 or PRIV-018 decided.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-08 | Recorded in M1-07, `Pending Analysis` | Technical Lead |
| — | 2026-10-08 | Packet revision (M1-08): normalized; recommendation added; status to `Ready for JJ Review` | Technical Lead |

### PRIV-020 — Deletion mechanics and interim deletion behavior

| Field | Value |
| --- | --- |
| Status | Ready for JJ Review |
| Decision owner | JJ |
| Technical owner | Technical Lead (Aries) |
| Legal/privacy review | Review Required |
| JJ decision | Pending |
| Decision evidence | — |
| Legal/privacy evidence | — |
| Decision date | — |
| Decision version | — |
| Implementation impact | Blocks M2 feature (user-facing deletion of Cases, Case Subjects, documents or Companies) |
| Implementation status | Technical foundation complete |
| Related decisions | PRIV-001, PRIV-002, PRIV-003, PRIV-004, PRIV-005, PRIV-008, PRIV-016, PRIV-018 |
| First recorded | M1-08 |

**Why a new ID.** PRIV-001 to PRIV-004 and PRIV-008 decide what happens to each
data category. None decides the cross-cutting mechanism (soft delete, hard
delete or anonymization) or what M2 may expose before those decisions are
approved. M1 already contains hard-delete functions and cascading foreign keys,
so the interim behavior must be explicit rather than implied by code.

**Question.**

1. Until PRIV-001 to PRIV-004, PRIV-008 and PRIV-016 are approved, may M2
   expose user-facing deletion of Cases, Case Subjects, documents or Companies?
2. Which deletion mechanism is the HeroOS default?

**Technical facts.** Company-scoped, RLS-protected hard-delete repository
functions exist (`delete_case`, `delete_case_subject`,
`delete_company_blueprint`). They are used by tests. No route exposes them.
Foreign keys cascade from `companies` and `users`, and deleting a Case Subject
sets `cases.subject_id` to NULL. Object deletion is an immediate hard delete. No
soft-delete columns exist.

**Options (interim, Q1).**

- A. No user-facing deletion in M2. Cases are closed, not deleted; mistakes are
  corrected by editing. Exceptional deletion (for example a wrongly entered
  employee) only through an operator-run, audited procedure.
- B. User-facing hard delete in M2, with an audit event.
- C. User-facing soft delete in M2 (hidden, still stored).

**Options (mechanism, Q2).** Hard delete; soft delete; anonymization; or a
choice per entity driven by PRIV-002, PRIV-003 and PRIV-008.

**Privacy implications.** B is irreversible before legal hold and backup rules
exist. C shows data as deleted while it is still stored. A keeps data until
policy exists, which is a temporary de facto retention that ends when the
retention decisions are approved.

**EU/GDPR-standard considerations.** Storage-limitation consideration and
handling of individual deletion requests during the interim. Not established in
engineering documentation; legal/privacy review required.

**UAE considerations.** Legal/privacy review required for UAE/DIFC
applicability.

**Cost / operational implications.** A is cheapest and keeps every later option
open. B is moderate and risky without PRIV-016. C adds a deleted filter to every
query, interacts with RLS policies and unique constraints, and is costly to
remove later.

**Engineering recommendation.** Q1: A. Q2: no universal soft delete (consistent
with the PRIV-002 recommendation); explicit lifecycle states (for example
active and closed) plus hard delete or anonymization per category once
approved. M2 schemas should not implicitly cascade-delete audit events
(PRIV-005) or a future deletion ledger (PRIV-018).

**Legal/privacy question.** Is pausing user-facing deletion until the retention
decisions are approved acceptable, and how are individual deletion requests
handled in the interim?

**Information required before decision.** None for JJ direction.

**Implementation traceability.** M1-04/M1-06 delete primitives: technical
foundation complete. M2 Case/Subject/document user-facing deletion: must
follow the approved interim rule.

**Re-review trigger.** PRIV-001, PRIV-002, PRIV-003, PRIV-004, PRIV-008 or
PRIV-016 decided.

**History.**

| Version | Date | Change | Authority |
| --- | --- | --- | --- |
| — | 2026-10-08 | Recorded in M1-08, `Ready for JJ Review` | Technical Lead |

---

## Important Principle: Retention

HeroOS will not assume that one fixed duration is automatically required by
GDPR or UAE law for every data category.

Retention should consider:

- purpose
- necessity
- employment/legal obligations
- dispute/audit requirements
- customer expectations
- storage limitation
- deletion/anonymization capability
- backup behavior
- operational cost

Technical cost and privacy justification must be presented separately.

Cheap storage does not by itself justify indefinite retention.

---

## Important Principle: AI Processing

Production AI processing must not begin with sensitive HeroOS customer data
until the selected provider and configuration have been reviewed for:

- data sent
- purpose
- processing region
- retention
- training/data-use policy
- subprocessors
- security
- contractual/privacy controls
- cost

HeroOS-approved content and deterministic Conditions remain authoritative
regardless of AI provider.

---

## Implementation Rule

A decision marked `Pending Analysis`, `Ready for JJ Review` or
`Legal Review Required` must not be treated as approved product policy.

Engineering may continue on unrelated technical controls.

For example, HeroOS may implement:

- encryption
- private S3
- tenant isolation
- authentication
- backup capability

without yet deciding:

- exact backup retention
- exact document retention
- exact case retention

The policy becomes implementation truth only after the required decision is
approved.

---

## Auditability

When a material decision is approved, record:

- decision
- approver
- decision date
- applicable legal review
- implementation references
- later superseding decision if any

Do not overwrite important historical decisions without preserving the reason
for the change. The mechanics are in §5.

---

## Appendix A — M1-07 Technical Inputs (No Policy Decided)

*Preserved as recorded in M1-07. Decision packets refer to these notes.*

M1-07 (secure storage, secrets, logging and backup foundation) implemented
technical capabilities only. It **did not** choose any retention period,
deletion policy, legal-hold rule, RPO or RTO. Every decision above remains
Pending. These notes record the current engineering behaviour and the options
each decision affects, so JJ and legal review can decide.

### PRIV-002 / PRIV-004 / PRIV-019: Objects and deletion

- Current behaviour: private objects are write-once. Deleting an object
  removes its bytes from the provider immediately (hard delete). No retention
  or lifecycle metadata exists, because the HeroOS Document domain and its
  metadata are M2.
- Options for production (S3, M3): (a) no versioning, so deletion is immediate
  and irreversible; (b) versioning with a lifecycle rule that expires
  non-current versions after an approved window, so a deleted object stays
  recoverable during that window; (c) object lock / retention for legal hold
  (PRIV-016).
- Implications: (b) improves recovery from mistakes or attacks but means
  "deleted" data persists for the window, which matters for PRIV-018. (c)
  prevents deletion entirely while active.
- Engineering will not enable versioning, lifecycle expiry or object lock until
  these decisions are approved.

### PRIV-006: Application logs

- Current behaviour: logs are minimized by design. They hold request IDs, route
  templates, status, duration, opaque Company/User UUIDs (after
  authorization) and exception types and locations. No headers, tokens,
  bodies, query strings, HR content or exception messages are logged
  ([Observability](../architecture/observability.md)).
- Remaining personal data in logs: opaque User/Company identifiers, which are
  pseudonymous rather than anonymous.
- Options: CloudWatch Logs retention is configurable per log group. No value is
  chosen. M3 must set an explicit, approved retention rather than the default
  "never expire".

### PRIV-007 / PRIV-017 / PRIV-018: Database backups and recovery

- Current behaviour: the logical backup procedure exists and is verified on
  disposable databases. Verification archives are deleted immediately after
  each run. No production backup exists.
- Options at M3: RDS automated backups with PITR (retention window
  configurable within AWS limits; no value chosen), manual snapshots (kept until
  deleted), and/or periodic logical dumps in an encrypted, access-controlled
  store.
- Implications: a longer window improves the achievable RPO and the ability to
  recover from late-detected problems, but keeps deleted or expired data
  recoverable for longer and costs more. Restoring a backup can bring back data
  that was deleted after it was taken. The recovery procedure therefore stops
  at "re-apply deletions per PRIV-018" and requires sign-off before a restored
  database is put into service.

### PRIV-008: Account / Company deletion

- Current behaviour: there is no Company deletion workflow. M1 schema foreign
  keys cascade at the database level, but no product path deletes a Company.
- Interaction: whatever Company deletion is approved must also define how
  that Company's objects (`companies/<company uuid>/…`), log entries and backup
  copies are treated (PRIV-004, PRIV-006, PRIV-018).

---

## Appendix B — Superseded Decision Record Template (M1-01)

The M1-01 template ("Question / Option A / Option B / Technical
Recommendation / Legal Confirmation Required / JJ Decision / Decision Date /
Implementation Impact") is replaced by the normalized packet format. Every
field it contained is kept in the new format. The original text is in commit
`66afc1b`.

---

## Change Log

| Date | Issue | Change |
| --- | --- | --- |
| 2026-10-07 | M1-01 | Register created with PRIV-001 to PRIV-015, all `Pending Analysis` |
| 2026-10-08 | M1-07 | PRIV-016 to PRIV-019 added, all `Pending Analysis`. M1-07 technical inputs recorded (Appendix A) |
| 2026-10-08 | M1-08 | Ownership, lifecycle, vocabularies, evidence rules and versioning defined (§1 to §5). Audit findings recorded (§6). M1-07 technical inputs moved to Appendix A unchanged |
| 2026-10-08 | M1-08 | Retention, deletion, legal-hold and backup/recovery packets completed (PRIV-001 to PRIV-008, PRIV-016 to PRIV-019). PRIV-020 added (deletion mechanics and interim behavior; no existing ID covered it). Status moves recorded in each packet history |
