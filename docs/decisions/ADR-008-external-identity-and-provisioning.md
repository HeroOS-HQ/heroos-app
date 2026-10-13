# ADR-008 — Provider-Independent Identity and Secure Provisioning

**Status (technical):** Proposed. Implemented on a feature branch for review; technical acceptance is the Technical Lead's, at merge review\
**Deployment and activation:** not authorized. Applying B1a/B1b, deploying the API and creating the operator login each need their own approval (pending decisions below)\
**Business policy:** the identity operator policy (D1–D6, R1–R3) is approved by
JJ and recorded in the [Identity Operator Access and Approval Policy](../operations/identity-operator-access-policy-proposal.md).
That approval covers business policy only: it does not accept this ADR's
technical design, does not mitigate the risks in §4, and is not a recorded
security-risk acceptance\
**Date:** 2026-10-12
**Owner:** Technical Lead
**Milestone:** M1-10 (HER-230), sub-issue M1-10B
**Related:** [ADR-003 Authentication](ADR-003-authentication.md),
[ADR-004 Data and Tenancy](ADR-004-data-and-tenancy.md),
[Authentication](../architecture/authentication.md),
[Tenant Isolation](../architecture/tenant-isolation.md),
[Identity Provisioning runbook](../operations/identity-provisioning.md),
[Decision Register](../privacy/decision-register.md)

## Context

Until M1-10B a verified identity was mapped to a HeroOS User by
`users.identity_subject` alone: one globally unique string, without the issuer.
Two identity providers could produce the same `sub`, moving from the temporary
OpenID Provider (Auth0) to Amazon Cognito (M5) meant overwriting the only
identity key, and there was no way to suspend a User or revoke a Membership
without deleting rows (PRIV-008, PRIV-020). Provisioning was hand-written SQL on
the live database.

## Decision

### 1. Identity

- `users.id` is the stable internal identity. It never changes when the identity
  provider changes, so audit actors and every reference stay valid.
- `user_identities` binds an external identity to a User by the **exact
  `(issuer, subject)`** a provider verified. Never normalized, never by email or
  any other claim. Unique for all time (`uq_user_identities_issuer_subject`): a
  revoked binding can never be re-bound to anyone. `user_id`, `issuer` and
  `subject` are immutable (column grants and a trigger). At most one *active*
  binding per User and issuer, so a User can hold an Auth0 and a Cognito binding
  at the same time during migration.
- The `AuthenticationProvider` protocol is unchanged: `VerifiedIdentity` already
  carried the issuer. `resolve_user` now returns internal IDs only
  (`ResolvedUser`), and `AuthenticatedCompanyContext` carries `identity_id`
  instead of the external subject.
- No just-in-time provisioning. A valid login without an active binding of an
  active User is denied with the same 403 as before.

### 2. Lifecycle (three non-overlapping states)

| Table | States | Scope | Meaning |
| --- | --- | --- | --- |
| `users.status` | `active` / `suspended` | global | the person is denied in every Company |
| `user_identities.status` | `active` / `revoked` | one credential binding | that login no longer maps to the User |
| `memberships.status` | `active` / `revoked` | one Company | access to that Company only |

Access needs all three active. They are checked on every request by the
application **and** by Row-Level Security for the API role (inactive rows are
invisible to `heroos_app_runtime`), so an access token that is still valid stops
working on the next request. Nothing is ever deleted: suspension and revocation
are not deletion. "Pending" is not a stored state: provisioning is atomic and
binds a subject the operator already knows.

### 3. Database roles

| Role | Identity privileges |
| --- | --- |
| `heroos_app_runtime` (API) | `SELECT` on `users`, `user_identities` (active rows only), `memberships` (active rows only). No write on any of them, no audit access |
| `heroos_identity_operator` (new NOLOGIN group; per-person `heroos_op_<handle>` logins) | From B1b: `SELECT, INSERT` and column-level `UPDATE (status, revoked_at/suspended_at, updated_at)` on `users`, `user_identities`, `memberships` (Memberships under the tenant RLS policy); `SELECT (id)` on `companies`. Nothing on `cases`, `case_subjects`, `company_blueprints`, the audit tables or `alembic_version`. No `DELETE`, no `TRUNCATE`. Never a member of `heroos_app_runtime` |
| Migration owner | Alembic migrations and the documented logical backup/restore procedure ([Backup and Recovery](../architecture/backup-and-recovery.md)). Never used by the API or the operator CLI. Any other use (for example the audit report of the operator policy) needs a recorded exception |
| Future background worker (ADR-009, not created) | No identity privileges; not a member of the runtime or operator group |

The API refuses to start with an operator login or with
`HEROOS_OPERATOR_DATABASE_URL` configured outside development. The operator CLI
refuses the migration owner, privileged roles and API runtime logins, requires
`sslmode=verify-full` for every host except a literal loopback address (and
refuses parameters or environment variables that could redirect a loopback
connection), and refuses any schema other than
contract 2. No HTTP route reaches the provisioning code (enforced by tests).

### 4. Provisioning

Only a platform operator provisions in M1-10B, with
`scripts/manage_identities.py` (provision, grant, bind-identity, revoke and
reactivate for Memberships and identities, suspend and reactivate Users). The
IdP account is created first, out of band (public sign-up disabled), so its
`sub` is known; HeroOS then creates the User, binding and Membership in one
transaction. Every command is idempotent. Subjects are read from standard input
and never printed. The first member of a Company is created the same way; the
first *administrator* needs the M1-10C role model.

#### Operator trust boundary: self-grant (residual risk, not mitigated)

An identity-operator login can, **alone and without any second person**, give any
external identity it can sign in with (including the operator's own IdP account)
an active Membership in **any** Company, and then read that Company's data
through the API like any member. Verified on a disposable PostgreSQL 17
(2026-10-13): provisioning the operator's own identity into one Company and
granting it two more succeeded, and its token was then authorized for all three.

- Nothing in the database ties an operator login to a HeroOS User, so a
  self-grant is technically indistinguishable from any other grant.
- The only control is detective: each change is audited with the operator's
  login (`db_role`, the authenticated `session_user`, which `SET ROLE` cannot
  change). The change reference is only format-checked: any well-formed issue
  key is accepted (for example a key that does not exist), so it records a
  claim, not an approval.
- The CLI is a convenience, not a boundary: the same login can make the same
  changes with plain SQL (still audited, still requiring a reference).
- Nobody reviews the audit trail yet, and no role other than the migration owner
  can read it.
- What does hold: the operator login cannot read HR tables or the audit tables,
  cannot delete anything, cannot disable the audit triggers, and cannot become
  the API runtime role or another login.

The same login can also suspend or revoke anyone (an availability risk).

**Business policy (approved by JJ, not a mitigation).** Only the Technical Lead
holds an operator login, in every environment including production (D1). There
is no mandatory second-person approval (D2), self-grants are unrestricted (D3,
R1), controls are procedural only (D5) and Company-access management is
unrestricted apart from issue references and audit records (R3). The findings
above therefore stay true in every environment. The only planned check is the
independent audit review of D4. No approved role may read the audit tables for
a report today, so the review becomes operable only once the minimum report
procedure is authorized (policy §4.1): a prerequisite for creating the operator
login, not for merging this code. The policy,
its residual-risk register and its open items are in
[Identity Operator Access and Approval Policy](../operations/identity-operator-access-policy-proposal.md);
operator procedures are in runbook
[§7](../operations/identity-provisioning.md#7-operator-trust-boundary-what-one-operator-login-can-do-alone)
and [§8](../operations/identity-provisioning.md#8-manual-audit-reports-d4-r2).

### 5. Audit

`identity_events` (global; owner-only, RLS without policies) and
`membership_events` (tenant-owned; standard `tenant_isolation` policy) are
written only by `SECURITY DEFINER` triggers (`search_path = ''`, `EXECUTE`
revoked from `PUBLIC`) in the same transaction as the change. They record the
authenticated `session_user`, an actor kind (`owner`, `operator`, `api`) and a
change reference that must be an issue key (or `alembic:<revision>` for the
migration owner); a change without a valid reference is rejected. Events never
copy the issuer or subject (`identity_id` is referenced instead). They are
append-only, also for the owner: row triggers refuse `UPDATE`/`DELETE` and a
statement trigger refuses `TRUNCATE`, including cascaded truncation. The
migration owner can still disable or drop those triggers or the tables; that is
a documented residual schema-owner capability (operator runbook §5). The only
control is keeping the owner credential out of every service. Shipping audit
events to immutable external storage, earlier planned for M5, is not approved:
R2 approves manual audit reports only. Retention is not set (PRIV-005).

Objects created by the migrations shed any privileges inherited from default
ACLs (for example Supabase's grants to `anon`, `authenticated`,
`service_role`); B1a verifies the exact ACLs on the server and refuses to run
while those well-known roles hold privileges on any HeroOS table. B1a and B1b
also refuse any role relationship that joins the runtime and operator groups
(inheritance either way, or a login in both); the local role bootstrap runs the
same checks before changing anything, in one transaction.

### 6. Migrations and rollback

- **B1a `b8a11c15ed91` (expand):** compatible with the previous API
  (`371dd50`). Adds the tables, lifecycle columns, policies, triggers, operator
  group and `heroos_schema_contract() = 1`, removes API write access to
  `memberships`, and backfills one binding per existing User. A non-empty
  database requires `-x legacy_identity_issuer=<exact issuer>` and
  `-x legacy_identity_user_count=<n>`; any mismatch aborts the whole migration.
- **B1b `09cb5ec569b9` (activate):** verifies every User has exactly one
  matching binding, drops `users.identity_subject`, grants the operator
  privileges and sets the contract to 2. From here the previous API fails closed
  (it maps the dropped column), so no lifecycle change can ever coexist with a
  schema the previous API could use.
- **Downgrades** refuse as soon as any change other than the B1a backfill has
  been audited (provisioning, suspension, revocation, reactivation or binding),
  whatever the current status values are. The supported recovery is
  roll-forward.
- Every safety check runs on the server (`DO` blocks), so it also holds in
  rendered `--sql` scripts.

### 7. Moving to Cognito (M5)

No business-authorization change: create the Cognito users, `bind-identity` a
Cognito binding for each existing `users.id`, switch configuration, verify, then
`revoke-identity` the old binding. Rollback before the revocation is a
configuration switch. Where M5 rebuilds RDS from synthetic data, Users are
simply provisioned with Cognito bindings.

## Consequences

- Business authorization, tenant isolation and workflow data never depend on
  the identity provider.
- Granting Company access is no longer possible through the API role; M1-10C
  must re-grant narrowly, behind permissions, when it adds admin endpoints.
- The audit tables and `RESTRICT` foreign keys mean Users, bindings and
  Memberships cannot be deleted until PRIV-005/008/020 decide how.
- Each deployed environment needs the Technical Lead's operator login (D1),
  created through an approved procedure (`bootstrap_runtime_role.py --operator`
  is local-only).

## Decided outside this ADR

| Decision | Decided by | Record |
| --- | --- | --- |
| Identity operator business policy: who holds operator logins (D1), approvals (D2), self-grants (D3, R1), audit review cadence (D4), procedural controls only (D5), opaque handles (D6), manual reports only (R2), unrestricted Company-access management (R3) | JJ | [Policy §2 and §8](../operations/identity-operator-access-policy-proposal.md#2-approved-decisions); JJ's approval date and written record not yet linked |

## Pending decisions (not approved by this ADR)

| Decision | Owner |
| --- | --- |
| Technical acceptance of this ADR (status stays Proposed) | Technical Lead |
| Lifecycle terminology (`active`/`suspended`, `active`/`revoked`) | JJ |
| Authorizing the minimum audit-report procedure (a recorded exception to the migration-owner scope in §3; [policy §4.1](../operations/identity-operator-access-policy-proposal.md#41-audit-table-access-for-reports-an-activation-prerequisite)); needed before creating the operator login | Technical Lead and JJ |
| Independent audit reviewer, report storage, per-change review deadline ([policy §7](../operations/identity-operator-access-policy-proposal.md#7-open-items-none-blocks-merging-the-code)) | JJ (with the Technical Lead for storage) |
| Security-risk acceptance for the residual risks, if intended ([policy §5](../operations/identity-operator-access-policy-proposal.md#5-residual-security-risks)); none is on record | JJ with the Technical Lead |
| Merging this ADR's implementation: merge-time checks G2, G6 and G7 recorded, G1 (Render Auto-Deploy Off) recommended; G1 is required before B1a ([runbook §3](../operations/identity-provisioning.md#merge-and-deployment-checks-render-github-supabase)) | Technical Lead |
| Audit-event retention | PRIV-005 (Legal Review Required) |
| User / Company deletion and the treatment of their audit events | PRIV-008, PRIV-020 |
| Role and permission model, Company administrators, approval authority, external experts | JJ, M1-10C |
| Production provisioning procedure (Cognito `AdminCreateUser` vs. invitations) | Technical Lead + JJ, M1-10D/M5 |
| Applying B1a/B1b to the Supabase demo and creating operator logins there | Separate infrastructure/deployment approval |
| Deploying the API to Render, and the deployment order (B1a, API, B1b) | Separate deployment approval |
