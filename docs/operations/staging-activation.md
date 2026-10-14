# Staging Activation Runbook: Identity, Company Registration and Onboarding

**Status:** Prepared in M1-10E. **Executed on the staging demo on 2026-10-14** (sections C, D and E; D7 and the operator checklist remain blocked): see the [close-out record](reports/2026-10-14-m1-10-staging-registration-closeout.md).
Every step needs its own explicit approval.\
**Owner:** Technical Lead (technical steps); JJ (product, privacy and policy approvals)\
**Scope:** The temporary demo: Vercel (web), Render (API), Supabase PostgreSQL, Auth0. Synthetic data only. No AWS.\
**Related:**
[Identity Provisioning §3](identity-provisioning.md#3-deploying-the-identity-migrations-approval-required),
[Company Registration §2–§3](company-registration.md),
[Backup and Recovery](../architecture/backup-and-recovery.md),
[Demo authentication deployment](demo-authentication-deployment.md),
[Staging test matrix](staging-e2e-test-matrix.md),
[Local end-to-end validation](local-end-to-end-validation.md)

This runbook takes the live demo from its current state to the merged code. It
covers M1-10B identities, M1-10C Company registration and roles, and M1-10D
onboarding. It then activates founder sign-up, as a separate step. Each step
lists its preconditions, the exact command, the postconditions to check and
where to stop.

**Rehearsed locally.** The whole database transition, with the API generations
each step expects, ran on a disposable copy:
- `e2e/suites/migration.mjs`, checks MIG-1 to MIG-29;
- the [M1-10E report §6](reports/2026-10-14-m1-10e-security-e2e-validation.md#6-database-migration-and-recovery).

A rehearsal is not the real thing. The real run still needs every gate below.

## A. Pre-deployment inventory (read-only, 2026-10-14)

"Unverified" means engineering could not read it without a private control
plane or credentials; it must be checked and recorded before step C1.

| # | Item | Value | How it was established | Status |
| --- | --- | --- | --- | --- |
| A1 | Web on Vercel Production | `db03f83` (M1-10D) | GitHub deployment records: Production deploy of `db03f83`, 2026-10-13 22:39Z, status success. Every merge to `main` has deployed Production | Verified |
| A2 | API on Render: generation | Older than M1-10C | `GET /me/companies` answers **404** (the route exists from M1-10C) | Verified |
| A3 | API on Render: exact commit | Before M1-10B (inferred) | An M1-10B or later API refuses to start without migration B1a (MIG-8, MIG-12), and `/health` answers 200 (after a 22 s cold start). Read the commit from Render's deploy history | **Unverified** |
| A4 | Render Auto-Deploy | Reported **Off** by the Technical Lead on 2026-10-12 | Not readable from GitHub | **Unverified now** (gate S1) |
| A5 | Supabase schema revision | Expected `97d4200fe7a2` (B1a never applied, per the records) | Not readable: engineering does not hold the credential | **Unverified** (step C0) |
| A6 | OIDC issuer | `https://heroos-demo.eu.auth0.com/`, **with** the trailing slash | Auth0's public discovery document | Verified (provider side) |
| A7 | `HEROOS_OIDC_ISSUER` on Render | Must be exactly A6 | Render environment | **Unverified** (gate S3) |
| A8 | Auth0 public sign-up and e-mail verification | On 2026-10-12 the hosted page showed a "Sign up" link | Auth0 dashboard | **Unverified** (gate S12) |
| A9 | `HEROOS_DEMO_COMPANY_IDS` on Vercel | Must still be set: with an API older than M1-10C, the web finds workspaces only through these candidates. Without them, signed-in users see "We can't reach HeroOS right now" | Vercel environment | **Unverified** (gate S10) |
| A10 | Operator logins | None created; the activation checklist of [Identity Provisioning §8](identity-provisioning.md#operator-activation-checklist) is incomplete | Records | Per records |
| A11 | Backup procedure | [Backup and Recovery §3–§5](../architecture/backup-and-recovery.md): `scripts.db_recovery`, which needs PostgreSQL client tools ≥ the server's major version (17 for Supabase) | Repository | Available; Supabase's own backups (plan-dependent) are unverified |
| A12 | Live web caching | Pages are served with `Cache-Control: public, max-age=0, must-revalidate` and `x-vercel-cache: HIT`. HTML is still rendered per request (fresh CSP nonce on each response) | Read-only `GET`s, signed out | Verified. M1-10E's back/forward-cache guard applies once deployed (D3) |
| A13 | `HEROOS_SELF_REGISTRATION_ENABLED` on Render | Must be unset or `false` until step E | Render environment | **Unverified** (gate S11) |

**What the live web does today (A1 + A2).**
- "Get started" opens Auth0's sign-up screen.
- A signed-in account without access sees the neutral welcome.
- Registration answers "Workspace setup isn't available yet", because the API has no registration route. Nothing can be created.

That is the M1-10D compatibility path working as designed. It also means that
**any account Auth0 lets sign up reaches the welcome page today** (A8).

## B. Pre-deployment safety gates

All of these must be recorded as satisfied, with evidence and no secrets, before
step C1.

| Gate | Check | Evidence |
| --- | --- | --- |
| S1 | Render API service Auto-Deploy = **Off** (identity runbook G1) | Settings screenshot or note |
| S2 | The API service's linked branch and currently served commit are recorded (G3); the commit predates M1-10B | Deploy history entry |
| S3 | `HEROOS_OIDC_ISSUER` on Render, copied verbatim, equals A6 (G4) | Value recorded (not a secret) |
| S4 | `MIGRATION_DATABASE_URL` and `HEROOS_OPERATOR_DATABASE_URL` are absent from the Render environment (G5) | Variable names listed |
| S5 | The migration credential is the Supabase owner role, separate from the runtime login, and kept only on the Technical Lead's workstation (libpq service + pgpass, 0600). The exact target is confirmed: project ref, host and database name | Target recorded; a read-only identity guard run before every change |
| S6 | A logical backup was taken **and** restored into a scratch database, then validated (Backup and Recovery §5) | Archive checksum, validation output |
| S7 | The demo database holds synthetic data only (no real customer or HR records) | Row review by the Technical Lead |
| S8 | A maintenance window is agreed. Not strictly needed: the order below keeps one working API generation at every step (MIG-7, MIG-10, MIG-14) | Window recorded |
| S9 | Roll-forward strategy accepted (section G); nobody plans to downgrade | Acknowledgement |
| S10 | No other deployment happens during the window. `main` is frozen, since every merge deploys Vercel Production. `HEROOS_DEMO_COMPANY_IDS` is set on Vercel (A9) | Freeze announced; variable name checked |
| S11 | `HEROOS_SELF_REGISTRATION_ENABLED` unset or `false` on Render | Variable checked |
| S12 | Auth0 sign-up state recorded (A8). If public sign-up is on and should not be, the Technical Lead decides whether to turn it off before C1. Engineering does not change provider settings | Decision recorded |

## C. Database transition (exact commands, in this order)

Run every command from a clean checkout of the approved `main` commit, as the
migration owner. The URL comes from the workstation's service file, never from
a command line. Stop at the first postcondition that fails, and do not
"continue to fix it".

**C0. Read-only baseline.**

```sql
SELECT version_num FROM alembic_version;                       -- expect 97d4200fe7a2
SELECT count(*) FROM users;                                     -- = n for C1
SELECT count(*) FROM users WHERE identity_subject IS NULL;      -- expect 0
SELECT count(*) FROM companies; SELECT count(*) FROM memberships;
```

Stop if the revision is not `97d4200fe7a2`, or if any user lacks a subject.

**C1. B1a: expand (approval: Technical Lead).** Old API stays up.

```bash
uv run alembic -x legacy_identity_issuer='https://heroos-demo.eu.auth0.com/' \
               -x legacy_identity_user_count=<n from C0> upgrade b8a11c15ed91
```

Postconditions:
- `SELECT heroos_schema_contract()` = 1;
- `SELECT DISTINCT issuer FROM user_identities` returns exactly A6;
- `SELECT count(*) FROM user_identities` = n;
- both demo users still sign in on the live (old) API.

A wrong count or a missing issuer aborts with nothing changed (MIG-4, MIG-5).

**C2. Deploy the M1-10B API `169261d` (approval).** Manual deploy of **that
commit**, not `main`: the API on `main` refuses to start before C1 (MIG-8).
Postconditions:
- `/health` is 200;
- no `IncompatibleSchemaError` or `UnsafeDatabaseRoleError` in the startup log;
- both demo users sign in and see their own Company;
- a cross-Company URL is denied (MIG-9).

**C3. B1b: activate (approval).** By revision:

```bash
uv run alembic upgrade 09cb5ec569b9
```

Never `upgrade head`: that would also apply C1. Postconditions:
- contract = 2;
- `users.identity_subject` is gone;
- the `169261d` API still serves (MIG-10).

An API older than M1-10B now answers 500 (fails closed, MIG-11). That is why
C2 comes first.

**C4. C1: Company registration and roles (approval).**

```bash
uv run alembic upgrade 3f6c2a9d81b4
```

Postconditions:
- contract = 3;
- `SELECT DISTINCT role FROM memberships` = `member` only. Nobody was promoted (MIG-16);
- every Company has a Blueprint; none has `employment_jurisdiction` (MIG-17, MIG-19);
- the `169261d` API still serves (MIG-14).

**C5. Deploy the current API (approval).** The approved `main` commit.
Postconditions:
- `GET /me/companies` without a token answers **401** (it was 404);
- signed in, each demo user discovers their Company **as member** (MIG-18);
- a cross-Company read is 403 (MIG-21);
- PATCH of the Blueprint is 403 until step D7 (MIG-20).

## D. Application verification

| Step | Check |
| --- | --- |
| D1 | Render: `/health` 200; `/openapi.json` 404; startup log clean; the runtime login is the RLS-restricted one |
| D2 | As owner: `SELECT heroos_schema_contract()` = 3 and `SELECT version_num FROM alembic_version` = `3f6c2a9d81b4` |
| D3 | Vercel: the deployed commit includes M1-10E. Response headers carry a nonce CSP and HSTS. After sign-out, Back shows no workspace (the M1-10E guard; matrix ST-19) |
| D4 | Discovery: each demo user lands on their own workspace; the chooser appears only for multi-Company users |
| D5 | Existing demo accounts: sign-in, workspace, cases, sign-out |
| D6 | Cross-tenant negatives in the browser and directly on the API (matrix ST-09) |
| D7 | **Administrators (approval, after the operator activation checklist).** Create the Technical Lead's operator login (identity runbook §1). Then, per demo Company: `set-role --company <id> --membership <id> --role company_admin` with an issue reference. Verify the `membership_role_changed` audit row and that PATCH now works (MIG-22) |
| D8 | Optional, after D4 passes: remove `HEROOS_DEMO_COMPANY_IDS` from Vercel. It is only a fallback for an API older than M1-10C |

## E. Founder sign-up activation (separate approval; not part of C/D)

Preconditions, all recorded:
- JJ's approvals:
  - the ADR-010 §8 privacy follow-ups (self-registered Users are personal-data subjects);
  - the one-self-service-Company-per-person rule;
  - retention and deletion (PRIV-005, PRIV-008, PRIV-018, PRIV-020) or an accepted interim.
- Abuse controls configured at Auth0 and checked: bot detection or attack protection, sign-up rate limits.
- An **e-mail verification policy** decided. HeroOS does not check `email` or `email_verified`: the API binds the verified subject only. If verified e-mail must come before registration, Auth0 must enforce it (for example, an Action that denies unverified sign-ins).
  Staging uses a Post Login Action scoped to the web client that calls
  `api.access.deny('email_not_verified')`. The web maps exactly that reason to
  `/?auth=verify_email`: a fixed "verify your email" message with *Sign in again*
  and *Use a different account* (the POST sign-out: RP-initiated logout at
  Auth0, which ends the Auth0 session). Auth0 first shows its own "log out?"
  confirmation, because HeroOS sends neither `id_token_hint` nor `logout_hint`
  (the web keeps no ID token, and a denied user never receives one); the user
  confirms once and returns to the homepage. Turning off the tenant's
  "RP-Initiated Logout End-User Confirmation" would remove that screen but also
  Auth0's protection against forged logout requests: keep it on. Any other
  denial stays "Sign-in was cancelled."; provider text is never rendered.
- Monitoring in place (F4).

Steps:
1. **Auth0** (by the Technical Lead; engineering never changes provider settings): enable sign-up on the Database connection, with the decided password and verification policy.
   For a demonstration limited to approved synthetic testers, keep the sign-up
   screen but make it invitation-only:
   - a Pre User Registration Action that refuses every address not in an Action
     secret allow-list (empty or missing list: refuse all), with a user-facing
     "Sign-up is by invitation only" message;
   - no social connection enabled for the HeroOS application: social logins
     create users without running Pre User Registration;
   - the verified-e-mail Post Login Action above, so an approved address only
     works for whoever controls its mailbox;
   - before activation, review the existing Auth0 users and block any account
     that is not a known tester or demo user (sign-up may have been public).
   Simpler still, without the sign-up screen: "Disable Sign Ups" on the Database
   connection and create each tester in the Auth0 dashboard (ST-01 is then not
   testable).
2. **Render:** `HEROOS_SELF_REGISTRATION_ENABLED=true`, then redeploy.
3. **Smoke tests:** matrix ST-01 to ST-08 with two fresh synthetic identities.
4. **Stop switch:** setting the flag to `false` stops new registrations at once. Existing workspaces stay. Disabling sign-up at Auth0 stops new accounts.

## F. Audit and privacy

- F1 **Operator policy.** No operator login before the activation checklist of
  [Identity Provisioning §8](identity-provisioning.md#operator-activation-checklist)
  is complete. Its known blocker: the independent review (D4) has no approved
  read path to the audit tables, because only the migration owner can read
  them.
- F2 **Audit verification** after every step: the report queries in
  [Company Registration §5](company-registration.md#5-audit-additions-to-the-identity-runbook-8-report)
  and Identity Provisioning §8. Expected events:
  - `company_registered` (actor `api`, `registration:<id>`);
  - `membership_role_changed` (actor `operator`, with the issue key);
  - `jurisdiction_confirmed`.
- F3 **JJ decisions still open** (none is approved by this runbook):
  - jurisdiction confirmation criteria (no real-customer confirmation until then);
  - the licensing-authority list;
  - the quiz;
  - retention and deletion;
  - whether a reverted licensing answer should reactivate an earlier confirmation (observed behaviour: it does, J-8);
  - e-mail verification before registration.
- F4 **Monitoring self-registration:** a daily read of
  `company_registrations` and `company_events` during the demo, and Auth0's
  sign-up logs. Unexpected registrations are suspended through the operator
  CLI. There is no delete command.
- F5 **Test identities and data.**
  - Staging tests use synthetic identities and Company names prefixed
    `[SYNTHETIC STAGING]`.
  - Their pseudonymous subjects are recorded in the issue, never in Git.
  - After testing they are suspended or revoked; nothing is deleted (PRIV-008, PRIV-020).

## G. Rollback and recovery

| What | Reversible? |
| --- | --- |
| Render API deploys | Yes, to an API generation that matches the schema. Before C3 any generation works. After C3 only `169261d` or later. After C4, `169261d` or the current API |
| Vercel deploys | Yes (redeploy a previous Production deployment) |
| `HEROOS_SELF_REGISTRATION_ENABLED`, Auth0 sign-up | Yes, immediately (existing registrations stay) |
| B1a, B1b | **Effectively forward-only** once any identity lifecycle change or audit row exists (their downgrades refuse) |
| C1 | **Forward-only** once any registration, role change, licensing answer or confirmation exists (refused: MIG-23) |
| Restoring a backup | Last resort only. It loses everything after the backup, its audit tables end at the backup time, and **it brings back access revoked after the backup** (demonstrated: MIG-27). The reconciliation gate (Backup and Recovery §4.7) is mandatory before any cutover |

Preferred recovery is roll-forward:
- a corrective migration;
- an operator correction (suspend, revoke, set-role);
- or an API redeploy.

Never downgrade casually.
