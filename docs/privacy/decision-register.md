# HeroOS V1 Privacy & Security Decision Register

**Owner:** Technical Lead  
**Business Decision Owner:** JJ  
**Milestone:** M1 — Foundation & Security  
**Last updated:** 2026-10-08

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

---

## Decision Status

- `Pending Analysis`
- `Ready for JJ Review`
- `Legal Review Required`
- `Approved`
- `Rejected`
- `Deferred`

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

## M1-07 Technical Inputs (No Policy Decided)

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

## Decision Record Template

For each decision that reaches JJ review, create a section using:

### PRIV-XXX — Decision Name

**Status:**  
**Decision Owner:** JJ  
**Technical Owner:** Aries  
**Legal Review:** Yes / No / Review Required

#### Question

What exactly must be decided?

#### Option A

Technical behavior:

Privacy implications:

EU/GDPR-standard considerations:

UAE considerations:

Cost implications:

Advantages:

Risks:

#### Option B

Technical behavior:

Privacy implications:

EU/GDPR-standard considerations:

UAE considerations:

Cost implications:

Advantages:

Risks:

#### Technical Recommendation

Aries recommendation and engineering rationale.

#### Legal Confirmation Required

State the exact question requiring legal confirmation.

#### JJ Decision

Pending.

#### Decision Date

Pending.

#### Implementation Impact

List the Linear issues / infrastructure / product behavior affected by the
decision.

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
for the change.