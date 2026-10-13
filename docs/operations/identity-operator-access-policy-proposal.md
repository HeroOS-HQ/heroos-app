# Identity Operator Access and Approval Policy

**Status:** Business policy **approved by JJ** (decisions D1–D6 and risk
resolutions R1–R3, §2). Recorded by engineering on 2026-10-13 from the
Technical Lead's written relay of JJ's decisions. JJ's own approval date and
written record were not available to engineering when this was recorded and are
not linked here (§8)\
**Decision owner:** JJ\
**Technical owner:** Technical Lead\
**Applies to:** identity operator logins and the operator CLI (ADR-008, M1-10B, HER-230)\
**Related:** [ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md),
[Identity Provisioning runbook](identity-provisioning.md),
[Decision Register](../privacy/decision-register.md) (PRIV-005)

What this approval is and is not:

- It **is** the business policy for who may operate identities and which
  approvals and reviews apply.
- It is **not** technical acceptance of ADR-008, which stays *Proposed*.
- It is **not** a technical mitigation of any risk in §5: the behaviour described
  there is unchanged by this policy.
- It is **not** a recorded security-risk acceptance. §5 states what such an
  acceptance would need; none is on record.

The file name keeps `-proposal` so existing links stay valid; the content is the
recorded policy.

## 1. Facts the policy applies to

Verified on a disposable PostgreSQL 17 on 2026-10-13 (ADR-008 §4, runbook §7).
One identity operator login can, on its own:

- give any identity that can sign in at the configured issuer, including the
  operator's own account, an active Membership in any Company, and then read
  that Company's data through the API;
- do the same with plain SQL instead of the CLI;
- attach any well-formed issue key as the change reference, including one that
  does not exist (the database checks the format only);
- suspend or revoke anyone, and reactivate anything.

Every change is written to the append-only audit tables with the operator's
login (`db_role`) and the reference. The operator login cannot read HR tables or
the audit tables, delete, disable the audit triggers, or change `db_role`.

## 2. Approved decisions

Recorded as relayed. Wording in the "Decision" column is JJ's.

| ID | Decision | Meaning for operations |
| --- | --- | --- |
| D1 | **A.** Only the Technical Lead may hold an identity operator login, including in production | Exactly one operator login per environment, held by the Technical Lead. Creating it on a deployed database still needs the separate deployment approval (ADR-008) |
| D2 | **A.** No mandatory second-person approval in any environment. Each operation still requires an issue reference and database audit | No approval step before any command. Every command carries `--reference <issue key>`; the database records it with the login |
| D3 | **C** (amended from A). Operator self-grants are unrestricted, including in production | The Technical Lead may grant their own identity access to any Company |
| D4 | **B** for the synthetic demo: independent monthly audit review. **C** for real customer data: independent weekly review plus review after every operator change | Review by someone other than the Technical Lead (§4). Operable once the activation prerequisites in §4.1 are met |
| D5 | **A.** Procedural controls only in every environment | No new technical enforcement is built for this policy. The controls that already exist in the schema and CLI (ADR-008) stay as they are |
| D6 | **A.** Opaque operator login handles. A secure mapping from handle to actual person is maintained by the Technical Lead | Logins are named `heroos_op_<opaque handle>` (for example `heroos_op_01`); the mapping is kept by the Technical Lead outside the repository |
| R1 | Unrestricted self-grants in all environments | Same as D3 |
| R2 | Manual audit reports only. No dedicated audit-reader role or immutable external log system is approved as part of this decision | Reports are produced by hand (runbook §8). The earlier plan to ship audit events to immutable storage at M5 is not approved by this decision |
| R3 | Unrestricted company-access management with issue references and audit records. No additional preventive company-scoped authorization is approved | Any Company, any command, no per-Company restriction beyond what ADR-008 already enforces |

Before the decision, engineering had recommended D3 = A everywhere and, before
real customer data, D1 = B (a named list), D2 = B and D5 = B. Those
recommendations are superseded by the decisions above and are not part of the
policy.

## 3. Operating rules that follow

| Role | Holder | Notes |
| --- | --- | --- |
| Identity operator | Technical Lead only (D1), opaque handle (D6) | One personal login per environment; never stored with a service |
| Handle-to-person mapping | Technical Lead (D6) | Kept securely outside the repository |
| Independent audit reviewer | Someone other than the Technical Lead (D4); **not yet named** | Reviews reports, records the review (runbook §8) |
| Migration owner | Technical Lead, for Alembic and the documented backup/restore procedure (ADR-008) | Unchanged by this policy; any other use, such as the audit report, needs the recorded exception in §4.1 |

| Command | Approval before the change | Record |
| --- | --- | --- |
| Every CLI command, including self-grants | None (D2, D3, R1, R3) | An issue whose key is passed as `--reference` and which records the change (runbook §2); the database audit event |

## 4. Audit review (D4, R2)

| Environment | Cadence | Reviewer |
| --- | --- | --- |
| Synthetic demo | Monthly (D4 = B) | Independent of the Technical Lead |
| Real customer data | Weekly, plus after every operator change (D4 = C) | Independent of the Technical Lead |

The manual report (R2) and its procedure (content, issue reconciliation,
delivery, proof of review, retention) are in
[runbook §8](identity-provisioning.md#8-manual-audit-reports-d4-r2).

### 4.1 Audit-table access for reports: an activation prerequisite

- `identity_events` and `membership_events` can be read only by their owner,
  the migration owner. The API runtime and operator roles have no privilege on
  them (by design, ADR-008 §5).
- ADR-008 limits the migration-owner credential to Alembic and the documented
  backup/restore procedure. Reading the audit tables for a report is neither.
- R2 approves no dedicated audit-reader role, and none is created.
- D1 puts the only operator login and the migration owner with the same person,
  the Technical Lead, so a report is prepared with the reported person's
  credential.

This does not block merging the M1-10B code: a merge activates nothing. The
operator group is created only by migration B1a and receives its privileges only
by B1b, and a merge applies neither. It blocks **operator activation**: the
Technical Lead's operator login is not created on any deployed database until
the procedure below is authorized in writing (runbook §8, activation checklist).

**Minimum safe procedure (selected; needs written authorization before
activation).** A witnessed, read-only report run by the migration owner, as set
out step by step in runbook §8. The authorization is a recorded, scoped
exception to ADR-008's migration-owner scope ("run the fixed audit report query,
read-only, witnessed by the independent reviewer"), approved by the Technical
Lead as ADR owner and by JJ as policy owner, and linked from runbook §8.

What it does **not** provide: it is procedural. Nothing in the database limits
the migration owner to read-only use, proves that the query was not edited, or
requires the witness; the read-only transaction only prevents writes inside that
transaction. The report is still produced with the reported person's credential
(§5, risk 6).

Alternatives considered and not selected (none creates a privilege):

| Alternative | Why not selected |
| --- | --- |
| Report from a restored logical backup (an existing, documented use of the migration owner) | Copies all HR data into another database for every report; freshness bounded by the backup; per-change reviews on real data would need a backup per change |
| The hosting provider's admin console used by the reviewer | Far broader access than a report needs; which role it uses for this project is not verified |
| No reports | D4 would not be met |
| Audit-reader role or immutable external log | Excluded by R2; would need a new decision |

## 5. Residual security risks

Approving D1–D6 and R1–R3 decides policy. It does not reduce these risks, and it
is not recorded as their acceptance: a security-risk acceptance would name the
risk owner, each risk accepted, the environments it covers and a review date.
Nothing of that kind is on record. Whether JJ's approval of R1–R3 is intended to
be that acceptance has to be stated explicitly.

| # | Risk | Verified facts | Existing technical limits (ADR-008) | Policy position |
| --- | --- | --- | --- | --- |
| 1 | Operator self-grant across Companies | One login can give its own identity a Membership in every Company and read their data through the API; no table links an operator login to a HeroOS User, so a self-grant looks like any grant | None that prevent it; every grant is audited with the login | Permitted (D3, R1, R3). Detective review only (D4), operable after the activation prerequisites (§4.1) |
| 2 | Compromised operator credential | Whoever holds it can grant any Company to any account that can sign in at the configured issuer, and suspend or revoke anyone. Its changes are indistinguishable from the Technical Lead's | Cannot read HR or audit tables, cannot delete, cannot disable triggers; per-person login on a workstation (`~/.pgpass`, 0600) | No time-boxing, second person or alerting (D2, D5). Under D1 the same person also holds the migration owner, so one compromised workstation can give both |
| 3 | Direct SQL bypass of the CLI | The CLI is a convenience; the same login can insert or update with plain SQL | The database grants, RLS and audit triggers apply to SQL exactly as to the CLI; a reference is still required | CLI use is procedure, not enforcement (D5) |
| 4 | Issue references are format-checked only | A nonexistent key such as `ZZ-9999999` is accepted | Format check in the trigger | Reconciled by hand in each report (runbook §8) |
| 5 | No preventive approval controls | Nothing stops a change before it happens | — | By decision (D2, D5, R3) |
| 6 | Manual report completeness | A report is a query run with a credential the reported person controls; it can be edited, filtered or run against the wrong database | Append-only audit tables. The totals check in runbook §8 shows a drop in the number of events between reports; it cannot show events that were never written (triggers disabled during a change) or a report altered before delivery | Manual reports only (R2); no external, immutable copy |
| 7 | Migration-owner powers over the audit structures | The owner can disable or drop the audit triggers or tables, or (as superuser) suspend all triggers | Credential custody only | No immutable external log approved (R2) |

## 6. Consistency check of D1–D6 and R1–R3 (2026-10-13)

The decisions do not contradict each other. How each implementation point is
handled:

1. **D4 needs audit-table access** that D1, R2 and the migration-owner scope do
   not provide. Handled as an activation prerequisite with a minimum procedure
   that needs authorization (§4.1). Not a code-merge blocker.
2. **"Independent" reviewer**: D4 requires one; none is named yet. Activation
   prerequisite.
3. **D4 = C per-change review on real data** has no deadline. Needed before
   real customer data.
4. **R2 versus the earlier M5 log-shipping plan**: ADR-008 §5 and runbook §5 had
   described immutable log shipping at M5 as a mitigation. Corrected: it is not
   approved and is not a current mitigation.
5. **D1 "including in production" versus the earlier interim rule** ("no
   operator login on databases with real customer data"): the interim rule was
   proposed in ADR-008 before the decision and is withdrawn. Creating any
   operator login on a deployed database still needs its own approval.
6. **D5 "procedural controls only"** is recorded as "build no new technical
   enforcement". The existing technical controls (grants, RLS, append-only
   triggers, CLI pre-flight refusals) remain.
7. **Migration-owner scope**: ADR-008 said "Alembic only" while the M1-07
   backup procedure already used the same role for `pg_dump`/`pg_restore`.
   Resolved: ADR-008 now states both uses; any other use, such as the audit
   report, needs a recorded exception (§4.1).
8. **D6 with D1**: with a single operator the opaque handle maps to one known
   person, so it gives little pseudonymity. Consistent; noted only.

## 7. Open items (none blocks merging the code)

| Item | Needed before | Owner |
| --- | --- | --- |
| Authorize the minimum audit-report procedure (§4.1) | Creating the operator login on any deployed database | Technical Lead and JJ |
| Name the independent reviewer | Creating the operator login on any deployed database | JJ |
| Agree the report storage and delivery location (runbook §8) | Creating the operator login on any deployed database | JJ and Technical Lead |
| Link JJ's written approval record and date (§8) | Creating the operator login on any deployed database | Technical Lead |
| Set a deadline for the per-change review (D4 = C) | Any real customer data | JJ |
| State whether a security-risk acceptance is intended for §5, and record it if so | Any real customer data (recommended) | JJ with the Technical Lead |

## 7a. M1-10C: new operator capabilities (for JJ, nothing decided here)

M1-10C ([ADR-010](../decisions/ADR-010-company-registration-and-administrators.md))
gives the same operator login three further capabilities, each audited with the
login and the issue reference like every other operator change:

- registering a Company with a verified identity as its first administrator
  (`register-company`);
- appointing or removing Company administrators (`set-role`);
- confirming or clearing a Company's employment jurisdiction
  (`confirm-jurisdiction`, `clear-jurisdiction`).

This record does **not** assume that D1–D6 and R1–R3 cover them. R3
("unrestricted company-access management") plausibly covers the first two;
jurisdiction confirmation is a legal judgement that R3 does not mention, and
its criteria are not approved. Until JJ states otherwise: these commands are
used on the synthetic demo only, and no jurisdiction is confirmed for real
customer data (ADR-010 §8).

Founder self-registration is **not** an operator capability: the API creates
the founder's own new Company through a database function, attributed to the
API login and the registration, not to an operator.

## 8. Decision record

| ID | Decision | Decided by | Approval date | Evidence |
| --- | --- | --- | --- | --- |
| D1 | A | JJ | Not provided | Relayed to engineering by the Technical Lead, 2026-10-13; JJ's record not linked |
| D2 | A | JJ | Not provided | As D1 |
| D3 | C (amended from A) | JJ | Not provided | As D1 |
| D4 | B for the synthetic demo (independent monthly review); C for real customer data (independent weekly review plus review after every operator change) | JJ | Not provided | As D1 |
| D5 | A | JJ | Not provided | As D1 |
| D6 | A | JJ | Not provided | As D1 |
| R1 | Unrestricted self-grants in all environments | JJ | Not provided | As D1 |
| R2 | Manual audit reports only; no audit-reader role or immutable external log approved as part of this decision | JJ | Not provided | As D1 |
| R3 | Unrestricted company-access management with issue references and audit records; no additional preventive company-scoped authorization | JJ | Not provided | As D1 |
