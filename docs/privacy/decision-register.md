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
| PRIV-001 | Active and closed Case data retention | Pending Analysis | Define retention based on product need, legal obligations and storage limitation rather than an arbitrary universal duration | Pending | Required |
| PRIV-002 | Closed-case deletion vs anonymization vs continued retention | Pending Analysis | Support explicit lifecycle behavior rather than universal soft deletion | Pending | Required |
| PRIV-003 | Employee / Case Subject data retention | Pending Analysis | Align retention with active case/company need and applicable legal requirements | Pending | Required |
| PRIV-004 | Uploaded and generated document retention | Pending Analysis | Keep document lifecycle configurable and tied to approved policy | Pending | Required |
| PRIV-005 | Audit-event retention | Pending Analysis | Preserve sufficient audit history while minimizing unnecessary sensitive content | Pending | Review Required |
| PRIV-006 | Application-log retention | Pending Analysis | Use minimized operational logs and shorter retention than business records unless operational need requires otherwise | Pending | Review Required |
| PRIV-007 | Database-backup retention | Pending Analysis | Balance recoverability with storage limitation and approved operational need | Pending | Review Required |
| PRIV-008 | Account / Company deletion behavior | Pending Analysis | Define controlled deletion/anonymization workflow rather than immediate unrestricted cascade deletion | Pending | Required |
| PRIV-009 | Production AI provider and model | Pending Analysis | Select only after capability, privacy, residency and cost comparison | Pending | Required |
| PRIV-010 | AI input/output retention | Pending Analysis | Prefer provider configuration minimizing or disabling provider retention where commercially/technically feasible | Pending | Required |
| PRIV-011 | AI provider training/data-use policy | Pending Analysis | Production customer data should not be used for general provider model training without explicit approved basis | Pending | Required |
| PRIV-012 | AI processing location / cross-border transfer | Pending Analysis | Evaluate actual provider processing location rather than assuming UAE hosting keeps AI processing in UAE | Pending | Required |
| PRIV-013 | Production data residency model | Pending Analysis | Keep primary HeroOS application/database/document infrastructure in AWS UAE; separately review every external processor | Pending | Required |
| PRIV-014 | Production subprocessor/vendor approval process | Pending Analysis | Maintain service inventory and review material data-processing changes before activation | Pending | Required |
| PRIV-015 | Transactional email content and retention | Pending Analysis | Minimize HR-sensitive content in email; prefer secure in-product access for sensitive case details | Pending | Review Required |
| PRIV-016 | Legal hold requirements | Pending Analysis | Define whether and when a legal hold suspends deletion of Cases, documents/objects, logs and backups before any automated deletion is implemented | Pending | Required |
| PRIV-017 | Recovery point objective (RPO) and recovery time objective (RTO) | Pending Analysis | Approve explicit RPO/RTO targets before M3 configures RDS backups/PITR and restore drills; engineering will present the cost of each option | Pending | Review Required |
| PRIV-018 | Deletion requests vs. existing backups, and treatment of restored backups | Pending Analysis | Decide whether deleted data may persist in backups until they expire, how such backups are protected meanwhile, and how deletions are re-applied after any restore | Pending | Required |
| PRIV-019 | Private object versioning and deleted-object recoverability | Pending Analysis | Decide whether S3 versioning / a recovery window applies to private objects, consistent with PRIV-004 and PRIV-018 | Pending | Review Required |

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
