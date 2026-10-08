# HeroOS V1 Privacy & Security Decisions — JJ Review Packet

**Prepared by:** Technical Lead\
**For:** JJ (business decision owner)\
**Milestone:** M1-08 — V1 Security & Privacy Decision Register\
**Prepared:** 2026-10-08\
**Source of truth:** [Privacy & Security Decision Register](decision-register.md)

## How to use this packet

- This packet is a short view of the register. Full analysis for each item is in
  the register packet with the same ID.
- **Nothing in this packet is approved.** Every JJ decision is `Pending`.
  Engineering recommendations are technical recommendations, not legal advice.
- Decide one item at a time. For each ID, reply in writing with one of:
  **Approve** (name the option), **Approve with conditions**, **Reject**,
  **Defer** (with a re-review trigger) or **Request further analysis**.
  Engineering records the reply in that register packet only. No other
  decision changes.
- No retention period, RPO or RTO value is proposed here. Where a value is
  needed, the packet says what information is still required.

## Overview

| Group | ID | Decision | Register status | Asked of JJ now |
|---|---|---|---|---|
| A | PRIV-020 | Deletion mechanics and interim deletion behavior | Ready for JJ Review | Decide |
| B | PRIV-014 | Production subprocessor/vendor approval process | Ready for JJ Review | Decide |
| B | PRIV-019 | Private object versioning | Ready for JJ Review | Choose direction |
| B | PRIV-011 | AI provider training/data use | Ready for JJ Review | Decide |
| B | PRIV-021 | AI input data categories and identifiability | Ready for JJ Review | Choose direction |
| B | PRIV-006 | Application-log retention | Pending Analysis | Business input only |
| B | PRIV-007 | Database-backup retention | Pending Analysis | Business input only |
| B | PRIV-017 | RPO and RTO | Pending Analysis | Business input only |
| B | PRIV-009 | AI provider and model | Pending Analysis | Nothing yet |
| B | PRIV-010 | AI input/output retention | Pending Analysis | Nothing yet |
| B | PRIV-012 | AI processing location | Pending Analysis | Nothing yet |
| C | PRIV-015 | Transactional email content | Pending Analysis | Nothing yet |
| D | PRIV-001 | Case retention | Legal Review Required | Route to legal/privacy |
| D | PRIV-002 | Closed-case deletion vs anonymization | Legal Review Required | Route to legal/privacy |
| D | PRIV-003 | Employee / Case Subject retention | Legal Review Required | Route to legal/privacy |
| D | PRIV-004 | Document retention | Legal Review Required | Route to legal/privacy |
| D | PRIV-005 | Audit-event retention | Legal Review Required | Route to legal/privacy |
| D | PRIV-008 | Account / Company deletion | Legal Review Required | Confirm scope; route to legal/privacy |
| D | PRIV-013 | Production data residency | Legal Review Required | Route to legal/privacy |
| D | PRIV-016 | Legal hold | Legal Review Required | Route to legal/privacy |
| D | PRIV-018 | Deletion vs backups; restored data | Legal Review Required | Route to legal/privacy |
| D | PRIV-022 | HeroOS data-protection role by processing activity | Pending Analysis | Answer business questions; route to legal/privacy |

Groups: **A** needed before M2 implementation. **B** needed before M3 production
activation or before any AI provider receives customer data. **C** may remain
pending without blocking engineering. **D** needs legal/privacy input before JJ
can finalize. None of these blocks closing M1-08.

## Standing request: legal/privacy reviewer

No legal/privacy reviewer is assigned (register §1). Group D cannot progress,
and no decision can record legal confirmation, until one is. **JJ is asked to
name who answers the legal/privacy questions in the register.**

---

## A. Needed before M2 implementation

### PRIV-020 — Deletion mechanics and interim deletion behavior

- **Register status:** Ready for JJ Review
- **Question:** Until the retention decisions (PRIV-001 to PRIV-004, PRIV-008,
  PRIV-016) are approved, may M2 let users delete Cases, Case Subjects,
  documents or Companies? Which deletion mechanism is the default?
- **Why now:** M2 builds Cases, documents and audit events. M1 already contains
  hard-delete functions and cascading foreign keys; without a decision they
  could become product behavior by default.
- **Options:** A. No user-facing deletion in M2 (close, don't delete; an
  operator-run, audited procedure for exceptions). B. User-facing hard delete.
  C. User-facing soft delete.
- **Privacy/compliance impact:** A keeps data until policy exists. B is
  irreversible before legal hold and backup rules exist. C shows data as deleted
  while it is still stored.
- **Cost/operations impact:** A cheapest and keeps every later option open. C
  adds permanent query and schema complexity.
- **Engineering recommendation:** A, and no universal soft delete.
- **Legal/privacy review:** Review Required (is the interim pause acceptable,
  and how are individual deletion requests handled meanwhile).
- **Implementation impact:** Blocks M2 user-facing deletion features.
- **JJ is asked to decide:** A, B or C for M2, and whether universal soft delete
  is ruled out.

## B. Needed before M3 production activation or AI activation

### PRIV-014 — Production subprocessor/vendor approval process

- **Register status:** Ready for JJ Review
- **Question:** (1) Is the service-inventory approval rule the gate for every
  vendor before it receives production customer data? (2) Are GitHub, Linear,
  Slack, the development VPS and the engineering AI development tool (Claude
  Code) confirmed as not approved for production customer HR data? (3) Who reviews vendor contracts and data-processing terms?
- **Why now:** M3 activates AWS services that will hold production data.
- **Options:** A. Approve the rule and (2). B. A plus commitments to customers
  about subprocessor changes. C. Defer until legal review.
- **Privacy/compliance impact:** Without a gate, data could reach unreviewed
  vendors. No data-processing agreement is documented in the repository for any
  vendor.
- **Cost/operations impact:** Light process; per-vendor legal review has a cost.
- **Engineering recommendation:** A now; B with legal input.
- **Legal/privacy review:** Required for vendor classification, which depends
  on HeroOS's own role (PRIV-022).
- **Implementation impact:** Blocks M3 production activation and external data
  processing.
- **JJ is asked to decide:** A, B or C, and name the contract reviewer.

### PRIV-019 — Private object versioning

- **Register status:** Ready for JJ Review
- **Question:** Should deleted documents be recoverable for a window (S3
  versioning with expiry), or should deletion be final?
- **Why now:** The S3 bucket configuration is set at M3.
- **Options:** A. No versioning. B. Versioning with expiry of old versions after
  an approved window. C. Object lock for legal hold, alone or with B.
- **Privacy/compliance impact:** B means deleted documents persist for the
  window. A gives deletion finality but no recovery.
- **Cost/operations impact:** B adds storage for old versions until expiry.
- **Engineering recommendation:** B, because deleted HR documents could
  otherwise never be recovered, and a database restore could reference missing
  documents. Window length decided later with legal input.
- **Legal/privacy review:** Review Required (for the window).
- **Implementation impact:** Blocks M3 S3 versioning and lifecycle
  configuration.
- **JJ is asked to decide:** direction A, B or C. Not the window length.

### PRIV-011 — AI provider training/data use

- **Register status:** Ready for JJ Review
- **Question:** May customer data sent to an AI provider be used for training or
  model improvement?
- **Why now:** It is a selection criterion for the AI provider (PRIV-009).
- **Options:** A. Prohibited; providers that cannot exclude HeroOS data are not
  eligible. B. Customer opt-in only. C. Allowed.
- **Privacy/compliance impact:** Under B or C, HR data would contribute to a
  model outside HeroOS control and could not be deleted afterwards.
- **Cost/operations impact:** A may narrow provider choice or need specific
  commercial terms.
- **Engineering recommendation:** A.
- **Legal/privacy review:** Required to confirm the chosen provider's terms; B
  or C would need legal confirmation first.
- **Implementation impact:** Blocks external data processing.
- **JJ is asked to decide:** A, B or C.

### PRIV-021 — AI input data categories and identifiability

- **Register status:** Ready for JJ Review
- **Question:** Which data may be sent to an AI provider, and may directly
  identifying employee data be sent?
- **Why now:** It shapes the design of any AI feature that sends Case content.
- **Options:** A. No personal data. B. Pseudonymized (identifiers replaced
  before sending). C. Identifiable, minimized. D. Exclude sensitive categories
  (for example health) in addition to B or C.
- **Privacy/compliance impact:** Free text can still contain identifiers. C
  sends identifiable HR data to a third party.
- **Cost/operations impact:** B needs a redaction layer and may reduce answer
  quality.
- **Engineering recommendation:** B with D.
- **Legal/privacy review:** Required; C would need legal confirmation first.
- **Implementation impact:** Blocks external data processing.
- **JJ is asked to decide:** the direction (A, B+D or C+D).

### PRIV-006, PRIV-007, PRIV-017 — Log retention, backup retention, RPO/RTO

- **Register status:** PRIV-006 Pending Analysis; PRIV-007 Pending Analysis;
  PRIV-017 Pending Analysis
- **Why:** M3 must set CloudWatch log retention, RDS backup retention/PITR and
  restore-drill targets explicitly.
- **What is missing:** candidate values with cost estimates (engineering, M3
  planning); for PRIV-017 also a measured restore time from the first M3 drill.
- **Engineering recommendation:** log retention shorter than business records;
  RDS automated backups/PITR as the baseline; targets accepted only after a
  restore drill meets them.
- **Legal/privacy review:** Review Required for all three.
- **JJ is asked now:** no decision. Optionally, state business expectations:
  how much recent data loss and how much downtime would be tolerable, and
  whether incident investigations need long log history.

### PRIV-009, PRIV-010, PRIV-012 — AI provider, AI retention, AI processing location

- **Register status:** PRIV-009 Pending Analysis; PRIV-010 Pending Analysis;
  PRIV-012 Pending Analysis
- **Why:** No AI provider may receive customer data until these are decided.
- **What is missing:** candidate providers, their terms, retention options,
  regions and subprocessors, and cost. The provider is TBD.
- **JJ is asked now:** nothing. Engineering will bring a provider comparison.

## C. May safely remain pending

### PRIV-015 — Transactional email content

- **Register status:** Pending Analysis
- No email feature is planned. Engineering recommends notification-only emails
  with a secure link. Needed only before the first email containing customer
  data.

## D. Needs legal/privacy input before JJ can finalize

These do not block current engineering. PRIV-020 (group A) covers M2 in the
meantime. Each register packet states the exact legal/privacy question.

| ID | Register status | Engineering recommendation (direction) | Legal/privacy question in short |
|---|---|---|---|
| PRIV-001 | Legal Review Required | Retention counted from Case closure; per-category or configurable period | Which periods or criteria apply to HR case records (UAE Federal / MOHRE, DIFC)? |
| PRIV-002 | Legal Review Required | Keep both deletion and anonymization possible; no universal soft delete | Is deletion, anonymization or restricted retention appropriate after the period? |
| PRIV-003 | Legal Review Required | Subject data follows its Cases | Employee data retention, leavers, and who handles employees' deletion requests |
| PRIV-004 | Legal Review Required | Documents follow their Case | Document-type-specific obligations? |
| PRIV-005 | Legal Review Required | Minimized audit events that may outlive Case data | Minimum/maximum periods for audit records? |
| PRIV-008 | Legal Review Required | Staged Company offboarding; User access removal first | Obligations at contract end; User erasure. JJ: confirm "Account" covers Company and User |
| PRIV-013 | Legal Review Required | UAE primary with approved exceptions (also blocks M3) | UAE Federal / DIFC residency and cross-border rules, including remote admin access |
| PRIV-016 | Legal Review Required | Application-level legal hold before any automated deletion | When must data be preserved, and who may instruct a hold? |
| PRIV-018 | Legal Review Required | Backups expire normally; deletion ledger; restore only into production-protected environments | Is persistence of deleted data in encrypted backups acceptable, and how is it disclosed? |

**JJ is asked now:** confirm that these questions go to the legal/privacy
reviewer, and confirm the PRIV-008 scope.

### PRIV-022 — HeroOS data-protection role by processing activity

- **Register status:** Pending Analysis
- **Question:** What is HeroOS's data-protection role toward customers and the
  individuals whose data it processes? It may differ per activity (Case
  processing, User accounts, logging, backups, AI, email, staff support access,
  any HeroOS use of customer data for its own purposes).
- **Why needed:** customer agreements, privacy notices, data-processing
  agreements, handling of individuals' requests, retention ownership and vendor
  classification (PRIV-014) all depend on it.
- **Options:** legal classifications per activity, decided by legal/privacy
  review. Engineering proposes no role.
- **Privacy/compliance impact:** until decided, none of the items above can be
  treated as settled.
- **Cost/operations impact:** legal review; later agreements, notices and
  possibly customer-facing request tooling. Not estimable before the outcome.
- **Engineering recommendation:** complete the processing-activity inventory,
  obtain legal classification before production customer data is accepted, and
  meanwhile build nothing that uses customer data for HeroOS's own purposes.
- **Legal/privacy review:** Required.
- **Implementation impact:** blocks the M3 production privacy posture, not
  current code development.
- **JJ is asked now:** answer the business questions in the register packet
  (own-purpose use of customer data; HeroOS staff access to Cases; who decides
  retention and deletion; planned customer terms), then route to the
  legal/privacy reviewer.
