# ADR-010 — Company Registration, Administrators and Jurisdiction Readiness

**Status (technical):** Proposed. Implemented on a feature branch (M1-10C) for review; technical acceptance is the Technical Lead's, at merge review\
**Product decision:** self-service founder registration, decided 2026-10-13 and relayed to engineering by the Technical Lead (§1). It supersedes the earlier "operator-assisted registration only" direction for M1-10C\
**Deployment and activation:** not authorized. Migration C1, the API deployment, `HEROOS_SELF_REGISTRATION_ENABLED` and the identity provider's public sign-up each need their own approval (§8)\
**Date:** 2026-10-13
**Owner:** Technical Lead
**Milestone:** M1-10C (Company Registration & Administrator Authorization); UI in M1-10D
**Related:** [ADR-008 Identity and Provisioning](ADR-008-external-identity-and-provisioning.md),
[ADR-004 Data and Tenancy](ADR-004-data-and-tenancy.md),
[Authentication](../architecture/authentication.md),
[Tenant Isolation](../architecture/tenant-isolation.md),
[Company Registration runbook](../operations/company-registration.md)

ADR-009 is reserved for the background worker (ADR-008 §3).

## Context

M1-10B (ADR-008) made identities provider-independent and put all provisioning
behind an audited operator CLI. It had no Company roles, no way to create a
Company, and the Company Blueprint had a single unvalidated
`primary_jurisdiction` label.

The product needs:

- founders to sign up and get a Company workspace immediately, as its first
  administrator, without waiting for anyone at HeroOS;
- a Company administrator who can maintain the Company Blueprint, and members
  who cannot;
- the Company's licensing information collected at onboarding (JJ, 13 October):
  "DIFC" or "Other", and for "Other" a licensing authority from a list JJ will
  provide; "Not sure" must stay unresolved;
- a safe answer to "may jurisdiction-specific guidance use this Company's
  context?" without inventing legal rules.

## Decision

### 1. Registration model (product decision, 2026-10-13)

Any founder or manager can sign up at the identity provider (Auth0 Universal
Login today: account, password, email verification), complete the HeroOS
onboarding form, and immediately get a new Company workspace as its first
administrator, without manual approval. Additional users of a Company join
through invitations in a later milestone (not built).

| Responsibility | Owner |
| --- | --- |
| Account registration, authentication, email verification, passwords | Identity provider |
| Company creation, Blueprint, licensing information, first administrator, workspace access | HeroOS |

Email verification is never treated as proof that someone legally represents a
company. Registration creates a workspace for the person who signed in; it is
not a legal claim, and the Company name and Blueprint are customer statements.

### 2. Founder self-registration (`POST /company-registrations`)

- The only API route an authenticated identity that HeroOS has not provisioned
  can reach. Every other route still resolves an active HeroOS User first and
  denies unknown identities with the generic 403 (ADR-008 §1 is amended
  accordingly; enforced by `tests/test_import_boundaries.py`).
- The issuer and subject come from the verified credential. The request body
  carries only the Company name and optional initial Blueprint answers; any
  user id, issuer, subject, Company id, role or administrator field is refused
  (422).
- The API role gets **one** new write capability: `EXECUTE` on the
  `SECURITY DEFINER` function `heroos_register_company(issuer, subject, name)`
  (pinned `search_path`, schema-qualified, no dynamic SQL, inputs re-validated).
  It holds no `INSERT`/`UPDATE` on `users`, `user_identities`, `memberships` or
  `companies`, so it cannot provision, grant or create anything any other way.
- The function, in the request's transaction: refuses a revoked binding or a
  suspended User; for a new identity creates the User and the exact
  `(issuer, subject)` binding; for an existing active User reuses it; always
  creates a **new** Company with a server-generated id, its empty Blueprint and
  a `company_admin` Membership, and records the registration. It can never
  attach anyone to an existing Company.
- **Idempotent per person:** one self-service registration per User
  (`company_registrations.user_id` is unique), serialized by transaction-level
  advisory locks on the identity and on the User. A retry, a double submit, a
  concurrent request or a sign-in through another binding of the same person
  (Auth0 and Cognito during M5) returns the same Company (`200`,
  `outcome: existing`) and its body is ignored. A further Company for the same
  person is created by an operator (§4). This limit is an engineering default
  (anti-abuse and idempotency), listed for JJ in §8.
- Audit: the existing triggers record `user_created`, `identity_bound`,
  `membership_granted` (role `company_admin`) and `company_registered` with
  actor `api`, the API login as `db_role`, and the reference
  `registration:<company_registrations.id>`. Only the API login can produce
  that reference form (checked by the trigger and the table constraints).
- Off unless `HEROOS_SELF_REGISTRATION_ENABLED=true` (404 otherwise), so
  deploying the code does not open public Company creation.
- `GET /me/companies` (the read-only function `heroos_identity_companies`)
  lists the caller's own active Memberships, which RLS otherwise hides, so a
  returning founder finds their workspace.

### 3. Company roles

`memberships.role` is `member` (default) or `company_admin`, a server-side fact
on the Membership row, carried in `AuthenticatedCompanyContext.role`. Never
derived from email, token claims (`cognito:groups`, `custom:*`), Company
names, frontend state or request fields.

| | `member` | `company_admin` |
| --- | --- | --- |
| Company profile, Blueprint and readiness (read) | yes | yes |
| Blueprint update (`PATCH /companies/{id}/blueprint`) | no (403) | yes |
| Change any role, invite, grant access | no | no (no route) |

- Administrator-only routes depend on `CompanyAdminDb`: the role is checked at
  authorization and checked again inside the write transaction, so a demotion
  or revocation is honoured on the next request.
- Migration C1 makes every existing Membership a `member`: nobody becomes an
  administrator by migration. Existing Companies get their administrator from
  an operator (`set-role`).
- Role changes are operator-only (`set-role`), audited as
  `membership_role_changed`. The API role has no write privilege on
  `memberships` at all; a Company administrator cannot appoint others until the
  invitation milestone decides how.
- Lifecycle is unchanged: a suspended User, revoked binding or revoked
  Membership loses administrator access on the next request.

### 4. Operator-assisted registration (kept)

The ADR-008 operator CLI gains `register-company` (a Company, its Blueprint and
its first administrator for a verified identity, keyed by a stable Company
UUID the operator records in the change issue), `set-role`,
`confirm-jurisdiction`, `clear-jurisdiction` and `jurisdiction-status`. For a
second Company of an existing founder, Companies that existed before roles,
or anyone who cannot self-register. The operator business policy (D1–D6,
R1–R3) is unchanged; how these capabilities relate to it is in §8.

### 5. Company Blueprint: four separate concepts

| Concept | Columns | Written by |
| --- | --- | --- |
| Customer's licensing answer | `licensing_location` (`difc` / `other` / `not_sure`), `licensing_authority` (only with `other`) | Company administrator (API), or at registration |
| Company-level employment jurisdiction | `employment_jurisdiction` (`uae_federal` / `difc` / `adgm` / `other`) | Trusted confirmation only (operator) |
| What the confirmation relied on | `confirmed_licensing_location`, `confirmed_licensing_authority`, `jurisdiction_confirmed_at` | Same confirmation |
| Case-specific jurisdiction facts | not here | Future workflows, per Case |

- The licensing authority is free text: JJ has not provided the approved list,
  and HeroOS does not invent one. It is never interpreted. When the list
  arrives it can become a validated code without changing the readiness rules.
- `primary_jurisdiction` (M1-04) is kept unchanged for existing rows, never
  read for readiness and not part of the API contract.
- The API role holds column-level `INSERT`/`UPDATE` on every Blueprint column
  **except** the four confirmation columns. Database `CHECK`s keep the answer
  and the confirmation consistent (all-or-nothing; a confirmation always
  records a definite answer, never "not sure").

### 6. Jurisdiction readiness

`app.companies.jurisdiction.assess_jurisdiction` is deterministic:

| Readiness | When | `guidance_allowed` |
| --- | --- | --- |
| `supported_confirmed` | a confirmed `uae_federal` or `difc`, and the customer's current licensing answer equals the one it was confirmed against | yes |
| `unsupported` | a current confirmation of `adgm` or any other jurisdiction | no |
| `unconfirmed` | everything else: no answer, "not sure", "Other" without authority, an answer not yet confirmed, or an answer changed since the confirmation | no |

- A licensing answer alone never establishes a jurisdiction: "Other" is never
  UAE Federal / MOHRE, "DIFC" is never automatically DIFC law. HeroOS has no
  approved licensing-to-jurisdiction mapping.
- Changing the answer withdraws the confirmation by itself.
- Future workflows call `require_supported_jurisdiction(scope)`, which returns
  the confirmed V1 jurisdiction or raises `JurisdictionNotReady` (block,
  clarify or escalate). There is no fallback regime.
- Registration and workspace access do not depend on readiness. Subscription
  eligibility (later) must require `supported_confirmed` at minimum.
- No jurisdiction quiz is built (deferred to JJ). The "not sure" result stays
  unresolved.

### 7. Database (migration C1 `3f6c2a9d81b4`, schema contract 3)

- `memberships.role`; Blueprint licensing and confirmation columns; an empty
  Blueprint for every Company without one.
- `company_events` (tenant-owned, append-only, trigger-written:
  `company_registered`, `jurisdiction_confirmed`, `jurisdiction_cleared`);
  `membership_events.role` and `membership_role_changed`;
  `company_registrations` (tenant-owned, append-only, function-written).
- API role: loses `INSERT`/`DELETE` on `companies`, Blueprint writes become
  column-level, gains `EXECUTE` on the two functions. Operator: `INSERT (id,
  name)` on `companies`, `INSERT (id, company_id)` and the confirmation columns
  on `company_blueprints` (plus `SELECT` on the licensing columns only, never
  the business profile), `UPDATE (role)` on `memberships`.
- All checks run on the server; C1 settles inherited default privileges and
  refuses to run while Supabase's API roles hold privileges. The M1-10B API
  keeps working on C1; the M1-10C API refuses to start before it.
- Downgrade refuses once any registration, role, licensing answer,
  confirmation or Membership change has happened since C1: roll forward.

## Consequences

- Founders onboard without HeroOS staff. Every self-registration is a new,
  isolated tenant with exactly one administrator.
- **Residual risk (new):** the API role can now create Users, bindings and
  Companies through `heroos_register_company`. A compromised API could create
  Companies for arbitrary identities. It still cannot grant access to any
  existing Company, change roles, or bypass lifecycle. (A compromised API
  could already read every tenant's data by setting the tenant context;
  RLS protects against application bugs, not a compromised runtime.)
- **Residual risk:** anyone who can create an account at the identity provider
  can create one Company per account. Bot protection and abuse limits at the
  provider, and HeroOS-side rate limits, are not built (§8).
- Every self-registered person has a HeroOS User and a stored subject:
  deletion (PRIV-008/020) and audit retention (PRIV-005) now matter for
  self-service users too.
- The web's demo Company discovery (`HEROOS_DEMO_COMPANY_IDS`) is superseded
  by `GET /me/companies` in M1-10D.

## 8. Pending decisions and approvals (not made by this ADR)

| Item | Owner | Blocks |
| --- | --- | --- |
| Technical acceptance of this ADR | Technical Lead | Merge |
| One self-service Company per person (engineering default); whether founders may self-register more | JJ | Nothing (operator covers more) |
| Whether the approved operator policy (R3) is meant to cover administrator appointment (`set-role`) and jurisdiction confirmation, which M1-10C adds to the operator's capabilities | JJ | Using those commands on real customer data |
| Which evidence justifies a jurisdiction confirmation (the confirmation criteria), and who may confirm | JJ (legal) | Confirming real customers; until then readiness stays `unconfirmed` |
| The licensing-authority list and any approved licensing-to-jurisdiction mapping | JJ | M1-10D second dropdown; nothing in M1-10C |
| Jurisdiction clarification quiz | JJ | Nothing (deferred) |
| Abuse controls for public sign-up (provider bot protection, rate limits) | Technical Lead | Enabling public sign-up |
| Applying C1 to the Supabase demo (after B1a/B1b), deploying the API, setting `HEROOS_SELF_REGISTRATION_ENABLED`, enabling Auth0 public sign-up | Separate deployment/activation approvals | Activation |
| Deletion of self-registered accounts and Companies | PRIV-008, PRIV-020 | Real customer data |
