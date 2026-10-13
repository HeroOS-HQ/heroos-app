# Identity Operator Access and Approval Policy — Proposal

**Status:** **Proposed. Not approved.** No decision below has been taken; nothing
here may be treated as approval\
**Decision owner:** JJ\
**Technical owner:** Technical Lead\
**Prepared:** 2026-10-13, for PR #16 (M1-10B, HER-230)\
**Related:** [ADR-008 §4](../decisions/ADR-008-external-identity-and-provisioning.md#operator-trust-boundary-self-grant-residual-risk-not-mitigated),
[Identity Provisioning runbook §7](identity-provisioning.md#7-operator-trust-boundary-what-one-operator-login-can-do-alone),
[Decision Register](../privacy/decision-register.md)

Engineering input for a business decision. It is not legal advice; anything
touching real customer personal data still needs the legal/privacy reviewer the
Decision Register calls for.

## 1. Why a decision is needed

M1-10B moves Company access out of hand-written SQL into a platform-operator
tool. Each operator gets a personal database login. Today, one such login can,
**alone**:

- give any identity it can sign in with (including the operator's own) access to
  **any** Company, and so read that Company's HR data through the product;
- suspend or revoke anyone, or undo another operator's revocation.

Every change is recorded with the operator's login, but the "change reference"
is only checked for format, nobody reviews the record, and the database cannot
tell a self-grant from any other grant. These facts were verified on a
disposable database on 2026-10-13 (ADR-008 §4).

Today only synthetic demo data exists. The questions below decide what must be
true before an operator login exists anywhere, and before any real customer data
does.

## 2. Proposed policy (for decision)

### Roles

| Role | Who (proposed) | Holds |
| --- | --- | --- |
| Identity operator | Named individuals only, listed in the access record (D1); one personal login each, never shared | An operator login for the environment they operate |
| Approver | JJ, or a delegate JJ names in writing; never the operator of the same change | Approves access-expanding changes (D2) |
| Audit reviewer | Someone who is not an operator (D4) | Reads the audit trail on a schedule |
| Migration owner | Technical Lead, for Alembic only | Unchanged by this policy (ADR-008 §5 residual) |

### Changes and the approval each needs

The principle: **removing access is fast, adding access needs a second person.**

| Change (CLI command) | Effect | Proposed rule |
| --- | --- | --- |
| `suspend-user`, `revoke-membership`, `revoke-identity` | Removes access | Any operator, immediately; issue opened at the latest the same day |
| `provision`, `grant` | Adds a person or Company access | Written request from the Company's authorized contact + approval by the approver before the change |
| `bind-identity` | Adds a login to an existing person | Approval before the change (it is how M5 moves users to Cognito) |
| `reactivate-*` | Restores access | Same as `grant`: approval before the change |
| Any change to the operator's **own** identity or User | Self-grant | Prohibited. Another operator performs it after approval |

The issue used as `--reference` is the approval record: requester, Company,
approver, date, and which person the identity belongs to (never the subject
value itself).

### Review

- The audit reviewer compares active Memberships and the audit events since the
  last review with the approved issues, and records the result.
- Proposed cadence: monthly while data is synthetic; weekly, plus after every
  operator change, once real customer data exists (D4).

## 3. Decisions requested from JJ

| ID | Question | Options | Engineering recommendation |
| --- | --- | --- | --- |
| D1 | Who may hold an operator login? | A. Technical Lead only. B. Named list approved by JJ. C. Any engineer | **A** during the synthetic demo; **B** before real customer data |
| D2 | Which changes need a second person? | A. None (record only). B. Access-expanding changes (table above). C. Every change | **B** before real customer data; **A** acceptable for the synthetic demo if D1 = A |
| D3 | Is operator self-grant allowed? | A. Prohibited. B. Allowed with approval. C. Allowed | **A** |
| D4 | Audit review: who and how often? | A. Not reviewed. B. Non-operator reviewer, monthly. C. Non-operator reviewer, weekly + per change | **B** for the synthetic demo; **C** before real customer data |
| D5 | Should engineering build technical enforcement? (cost noted in §4) | A. Procedural only. B. Time-boxed logins + audit-reader role. C. B + two-person enforcement in the CLI | **B** before real customer data; **C** to be costed for M5 |
| D6 | Operator attribution: opaque handles or named logins; where the mapping lives (already open in ADR-008) | A. Opaque handles, mapping kept by the Technical Lead. B. Named logins | Engineering has no strong preference; it is an operator-personal-data question |

Nothing in this table is decided. Until JJ records a decision, engineering
follows the interim restriction proposed in ADR-008 (itself still Proposed):
operator logins only on the synthetic demo, none on any database holding real
customer data, and none created anywhere without the separate deployment
approval.

## 4. What exists and what would have to be built

| Control | Today | To build (if chosen) |
| --- | --- | --- |
| Personal operator logins, attribution by login | Exists (`db_role` = authenticated login) | — |
| Operator cannot read HR data or audit tables, cannot delete, cannot disable audit | Exists, verified | — |
| Change reference is a real, approved issue | Format check only | Check against the issue tracker in the CLI (D5 C); the database itself cannot verify it |
| Second person before access-expanding changes | Not enforced | Procedural (D2), or CLI enforcement (D5 C) |
| Detecting self-grant | Not possible in the database | Procedural review (D4); or record each operator's own `user_id`s and refuse them in the CLI |
| Reading the audit trail without the migration owner | Not possible | A read-only audit-reader role (small migration) |
| Logins valid only for a change window | Not used | `VALID UNTIL` on the login, set per change window (no code change) |
| Alerting on operator changes | None | M5 log shipping |

## 5. Decision record

| ID | Decision | Conditions | Decided by | Date |
| --- | --- | --- | --- | --- |
| D1 | — | — | — | — |
| D2 | — | — | — | — |
| D3 | — | — | — | — |
| D4 | — | — | — | — |
| D5 | — | — | — | — |
| D6 | — | — | — | — |
