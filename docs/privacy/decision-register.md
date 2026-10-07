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