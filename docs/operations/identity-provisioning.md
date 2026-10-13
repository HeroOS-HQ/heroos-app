# HeroOS Identity Provisioning (Operator Runbook)

**Status:** Implemented on a feature branch (M1-10B); nothing here has been run against
a deployed database\
**Owner:** Technical Lead\
**Related:** [ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md),
[Authentication](../architecture/authentication.md),
[Tenant Isolation](../architecture/tenant-isolation.md),
[Backup and Recovery](../architecture/backup-and-recovery.md),
[Database Credentials](database-credentials.md)

Every step that touches a deployed database, an identity provider or a
deployment needs explicit approval first. Data in the temporary demo is
synthetic only.

## 1. Roles and credentials

| Credential | Who holds it | Never |
| --- | --- | --- |
| API runtime login (`heroos_app`) | the API service (`DATABASE_URL`) | provisioning; the operator CLI refuses it |
| Identity operator login (`heroos_op_<handle>`) | the Technical Lead only, in every environment including production (policy D1); on their workstation only (`~/.pgpass`, 0600) | the API, Render, Vercel or CI. The API refuses to start with it |
| Migration owner | Technical Lead, for Alembic only | the API or the operator CLI (both refuse it) |

Handles are opaque, for example `heroos_op_01` (policy D6). The Technical Lead
keeps the handle-to-person mapping securely, outside the repository. The
business policy for operators is recorded in the
[Identity Operator Access and Approval Policy](identity-operator-access-policy-proposal.md)
(approved by JJ; ADR-008 itself is still Proposed).

### Creating an operator login

- **Local development / CI:** with `MIGRATION_DATABASE_URL` and
  `HEROOS_OPERATOR_DATABASE_URL` (a `heroos_op_*` login and a generated
  password) in the environment,
  `cd apps/api && uv run python -m scripts.bootstrap_runtime_role --operator`.
  It refuses non-local hosts.
- **Deployed database (approval required):** only for the Technical Lead
  (policy D1), as the migration owner, after B1b:

  ```sql
  CREATE ROLE heroos_op_<handle> LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE
      INHERIT CONNECTION LIMIT 2 PASSWORD '<client-side SCRAM verifier>';
  GRANT heroos_identity_operator TO heroos_op_<handle>;
  ```

  Generate the verifier client-side (`scripts/scram.py`), never send a plaintext
  password, and verify afterwards that the login is not a member of
  `heroos_app_runtime`. On Supabase the login is used as
  `heroos_op_<handle>.<project-ref>` through the session pooler with
  `sslmode=verify-full`.

## 2. Using the CLI

```bash
cd apps/api
export HEROOS_OPERATOR_DATABASE_URL='postgresql+psycopg://heroos_op_<handle>@<host>:<port>/<db>?sslmode=verify-full&sslrootcert=<ca file>'
# The password comes from ~/.pgpass; never put it in the URL or on the command line.

# New person: create the IdP account first (admin console, public sign-up off) and copy its `sub`.
# Read it silently into a shell variable: it is never typed as a literal, so it
# is not echoed and never reaches shell history or a process argument list
# (printf is a shell builtin; the CLI reads it from standard input).
IFS= read -rs HEROOS_SUBJECT
printf '%s\n' "$HEROOS_SUBJECT" | uv run python -m scripts.manage_identities \
    --expect-database <db> --reference HER-230 \
    provision --company <company uuid> --issuer '<exact issuer>'
unset HEROOS_SUBJECT
```

- Never write a subject as a literal in a command (`echo 'auth0|…' | …`,
  `<<< 'auth0|…'`): shell history records it. Do not keep subjects in files.
- TLS: only a literal loopback host (`localhost`, `127.0.0.1`, `::1`, e.g. the
  local Compose port `127.0.0.1:5433`) may connect without TLS. Every other
  host, including Compose service names such as `db`, requires
  `sslmode=verify-full`. The URL must not contain `host`, `hostaddr` or
  `service` parameters, and for loopback URLs `PGHOSTADDR`, `PGSERVICE` and
  `PGSERVICEFILE` must be unset: each could redirect the connection.

| Command | Effect |
| --- | --- |
| `provision --company --issuer` (+ subject on stdin) | new User + binding + Membership (one transaction) |
| `grant --company --issuer` (+ subject) | Membership for an existing active binding |
| `revoke-membership` / `reactivate-membership --company --membership` | one Company only |
| `bind-identity --user --issuer` (+ subject) | additional binding (e.g. Cognito at M5) |
| `revoke-identity` / `reactivate-identity --identity` | one login binding |
| `suspend-user` / `reactivate-user --user` | the person, in every Company |

- The issuer must be exactly what the provider puts in `iss` (Auth0 keeps a
  trailing slash). A wrong issuer simply never matches (fail closed).
- `--reference` must be an issue key. The database rejects any change without
  one, and records it with your login in the audit tables. It checks the format
  only, so the issue itself is the change record (below).
- No approval is needed before any command, including a grant to your own
  identity (policy D2, D3, R1, R3).

**Change record (policy D2).** Every operation has an issue, and its key is the
`--reference`. Engineering procedure, so that the audit review (§8) can
reconcile every event:

1. Before the command, the issue states the command, the Company UUID (if any),
   the reason, and whether the identity is the operator's own (self-grants are
   permitted; recording them keeps the review complete).
2. After the command, paste the CLI's JSON output (outcome and internal IDs
   only) into the issue.
3. Never put an external subject, an email address or other personal details of
   the person in the issue; internal IDs are enough.
4. One issue may cover several commands of the same change; a refused command is
   recorded too.
- Output is JSON with an outcome (`created`, `updated`, `unchanged`, `refused`)
  and internal IDs; subjects are never printed. Exit codes: 0 done, 2 usage,
  3 pre-flight refused, 4 operation refused, 5 database error.
- Suspension or revocation takes effect on the API's next request. Also disable
  the account at the identity provider, so it cannot obtain new tokens.

## 3. Deploying the identity migrations (approval required)

### Pre-merge safety gate (Render)

Merging this work into `main` must not deploy anything. Before the merge, every
row below is checked and recorded with evidence (no secrets) in the pull
request. A row without evidence means: do not merge.

| # | Check | How | Why |
| --- | --- | --- | --- |
| G1 | Render API service **Auto-Deploy = Off** | Render dashboard → the API service → Settings → Auto-Deploy | Render's options are *On Commit* (deploys on every push or merge to the linked branch; the default for new services), *After CI Checks Pass* (still deploys after the merge, once CI is green) and *Off*. Only *Off* keeps the merge from becoming a deployment |
| G2 | Nothing else deploys the API on a push to `main` | Render → the service's deploy hook is not called by any automation; GitHub → organization Settings → GitHub Apps → Render → repository access | The Render GitHub App is installed on the organization (selected repositories). This repository has no deploy workflow (`.github/workflows/ci.yml` only builds and tests), no repository webhooks and no deploy-hook call |
| G3 | The service's linked branch and the commit it currently serves are recorded | Render → the service's settings and deploy history | Must be a commit from before this work (no `user_identities` code); B1a is compatible with it |
| G4 | `HEROOS_OIDC_ISSUER` copied verbatim from the service environment | Render → the service → Environment (not a secret) | Needed for the B1a `-x legacy_identity_issuer`; a mismatch makes every sign-in fail closed |
| G5 | `HEROOS_OPERATOR_DATABASE_URL` and `MIGRATION_DATABASE_URL` absent from the service environment | Render → the service → Environment | The new API refuses to start with either outside development |
| G6 | All six CI jobs green on the merge commit (Web, API, Containers, Tenant Isolation, Backup & Restore, Privacy Decisions) | Pull request checks | The `main` ruleset requires only Web and API, so a failing security gate would not block the merge on its own |
| G7 | No Supabase migration is applied by the merge | Repository has no `supabase/` directory; the Supabase GitHub integration reports "skipped" on this pull request | Alembic migrations are applied only by hand (step 3 below) |

If G1 cannot be confirmed, do not merge. What would happen otherwise: before
B1a, the new API exits at startup because `heroos_schema_contract()` is missing
and never serves its port (verified on a disposable PostgreSQL 17, 2026-10-13;
`/health` itself does not touch the database). Render's documentation says a
deploy that fails to start is abandoned and the previous deploy keeps serving;
that has not been tested against this service. After B1a, the merge would
deploy the new API without its own approval. Neither is acceptable as a plan.

Merging also triggers a Vercel production build of the web; `apps/web` is
unchanged by this work, so that build serves the same web code.

**Evidence recorded by engineering for PR #16 (2026-10-13, head `c14969a`).**
Read-only checks of the repository and GitHub. No Render, Supabase or Vercel
setting was inspected. **No row is satisfied.**

| # | Evidence so far | Still to check | Status |
| --- | --- | --- | --- |
| G1 | None | Auto-Deploy setting in Render | Open |
| G2 | Only `.github/workflows/ci.yml` exists; 0 repository webhooks; no deploy-hook call in the repository; the Render GitHub App is installed on the organization with *selected* repository access | Whether that access includes this repository; whether anything outside the repository calls the service's deploy hook | Open |
| G3 | None | Linked branch and the commit the service serves | Open |
| G4 | None | Issuer value in the service environment | Open |
| G5 | None | Service environment variables | Open |
| G6 | All six jobs green on the PR head `c14969a`; the `main` ruleset requires only Web and API, with 0 approving reviews | The merge commit does not exist yet | Open |
| G7 | No `supabase/` directory at `c14969a`; the Supabase GitHub check reports "skipped" on `c14969a` | The Supabase project's GitHub integration settings | Open |

Order, for a database that already has users:

1. The pre-merge safety gate above is recorded as satisfied, and the API host
   still does **not** auto-deploy from `main`.
2. Take a logical backup ([Backup and Recovery](../architecture/backup-and-recovery.md)).
3. Count users and read the exact configured issuer (`HEROOS_OIDC_ISSUER`, not
   secret). Then, as the migration owner, from a clean checkout:

   ```bash
   uv run alembic -x legacy_identity_issuer='<exact issuer>' \
                  -x legacy_identity_user_count=<n> upgrade b8a11c15ed91
   ```

   Any mismatch aborts with nothing changed. The previous API keeps working.
4. Verify: `SELECT DISTINCT issuer FROM user_identities` equals the configured
   issuer; one binding per user.
5. Deploy the new API (it refuses to start on a schema older than B1a).
6. Smoke test sign-in for every user and cross-Company denial. The web lists
   only the candidate Companies the API authorizes, so a user must see exactly
   their own Companies (and, with none, the "no access" message).
7. `uv run alembic upgrade head` (B1b). The previous API can no longer resolve
   anyone (fail closed).
8. Only with its own approval: create the Technical Lead's operator login (§1,
   policy D1). Until the audit-report access issue (§8) is resolved, operator
   changes on that database cannot get the independent review policy D4
   requires.

## 4. Rollback

| Situation | Action |
| --- | --- |
| After B1a, before B1b | Redeploy the previous API if needed (compatible). `alembic downgrade 97d4200fe7a2` is allowed only while nothing but the backfill has been audited |
| After B1b, nothing provisioned, suspended, revoked or reactivated | `alembic downgrade b8a11c15ed91` restores `users.identity_subject` |
| After any such change | **Roll forward.** Both downgrades refuse (they inspect the audit history, not just current status), and the previous API fails closed on B1b |

Never edit `alembic_version`, disable triggers or re-add the legacy column by
hand: that would let the previous API ignore suspensions and revocations.

## 5. Audit integrity: what append-only does and does not cover

- `identity_events` and `membership_events` refuse `UPDATE`, `DELETE` and
  `TRUNCATE` (including cascaded truncation such as `TRUNCATE users CASCADE`)
  for every role, the migration owner included. The API and operator roles
  hold no privilege on them at all.
- **Residual migration-owner capability:** the owner can still disable or drop
  the triggers, drop the tables, or (as a superuser) set
  `session_replication_role = replica`, which suspends all triggers. These are
  deliberate schema-owner powers, not protected against inside the database.
  Control: the owner credential is held by the Technical Lead for Alembic only,
  never by a service. Shipping audit events to separate immutable storage
  (earlier planned for M5) is not approved: policy R2 approves manual audit
  reports only. The disposable test suites use the superuser-only replica switch
  to reset their own databases.

## 6. Restoring a backup: reconciliation gate (fail closed)

A backup from before a suspension or revocation still contains the old, active
state. The restored database's own audit tables end at the backup time, so they
cannot show later changes, and a list of issue keys is **not** enough to replay
lifecycle state. Therefore:

1. Restore into a new database. **Do not** point the API's `DATABASE_URL` at it
   and do not create or enable the API login on it yet.
2. Reconcile every restored binding and Membership independently, from sources
   that do not come from the restored database:
   - the pre-incident database, if it is still readable: compare `users`,
     `user_identities`, `memberships` (status) and the audit events newer than
     the backup;
   - the identity provider: every disabled or deleted account must have its
     binding revoked;
   - the Company's own confirmation of who should have access.
3. Anything that cannot be reconciled is suspended (User) or revoked
   (Membership, binding) with the operator CLI before traffic.
4. Record the reconciliation (who, when, sources, result) and get Technical Lead
   (and, for customer data, JJ) sign-off. Only then point the API at the
   restored database.

There is no external journaling service in M1-10B; this gate is procedural.

## 7. Operator trust boundary: what one operator login can do alone

Read this before anyone is given an operator login
([ADR-008 §4](../decisions/ADR-008-external-identity-and-provisioning.md#operator-trust-boundary-self-grant-residual-risk-not-mitigated)).

| An operator login alone **can** | An operator login **cannot** |
| --- | --- |
| Give any identity it can sign in with, including the operator's own IdP account, an active Membership in any Company (only the Company's UUID is needed; UUIDs are not secret), then read that Company's data through the API | Read `cases`, `case_subjects`, `company_blueprints` or the audit tables directly |
| Do the same with plain SQL instead of the CLI | Delete or truncate Users, bindings, Memberships or audit events |
| Attach any well-formed issue key as `--reference`, including one that does not exist | Disable the audit triggers or change `db_role` (`SET ROLE`/`SET SESSION AUTHORIZATION` are refused) |
| Suspend or revoke anyone, or reactivate what another operator revoked | Become the API runtime role |

Under the approved business policy
([policy §2](identity-operator-access-policy-proposal.md#2-approved-decisions)):

- The only operator is the Technical Lead, in every environment (D1). Every
  capability in the left column is permitted, including self-grants (D3, R1,
  R3), with no approval before the change (D2) and no new technical control
  (D5). The table describes behaviour the policy accepts; it does not mitigate
  it.
- A self-grant cannot be detected in the database: no table links an operator
  login to a HeroOS User. It is visible only through the change record (§2),
  which the operator writes, and the independent review (§8).
- Every change has its issue (§2); the reference is the operator's claim, not
  proof of approval or of the issue's existence.
- Residual risks and their status: [policy §5](identity-operator-access-policy-proposal.md#5-residual-security-risks).

## 8. Manual audit reports (D4, R2)

> **Blocked.** Only the migration owner can read `identity_events` and
> `membership_events`, and ADR-008 limits that credential to Alembic. No
> approved path exists for producing a report
> ([policy §4.1](identity-operator-access-policy-proposal.md#41-unresolved-no-approved-way-to-read-the-audit-tables-for-a-report)).
> This section defines the procedure; it cannot be run until the Technical Lead
> and JJ choose an access path. No new database privilege is to be created for
> it without a separate decision (R2).

| Topic | Procedure |
| --- | --- |
| Prepared by | The Technical Lead, through the access path chosen under policy §4.1. The preparer is the reported operator; that limits what the review can prove (policy §5, risk 6) |
| Reviewed by | An independent reviewer: someone other than the Technical Lead, named by JJ (not yet named) |
| Cadence | Synthetic demo: monthly. Real customer data: weekly, and after every operator change (D4; no deadline set yet for the per-change review) |
| Period | Half-open, in UTC: it starts exactly at the previous report's end and ends at this report's cut-off, so no event falls between two reports. The first report starts when B1a was applied |
| Content | Sections 1–5 of the query below, unedited, plus a header: report ID, environment, database name, period, previous report ID, preparer handle, reviewer, Git commit of this runbook, and the Technical Lead's own HeroOS `user_id`s (self-declared, for spotting self-grants) |
| Never in a report | External subjects, email addresses or names; the report uses internal IDs only |
| Issue reconciliation | Every `actor_reference` in section 4 must be an existing issue that records the change (§2). `alembic:<revision>` references must match a recorded migration run. A missing issue, an issue that does not describe the events, or events without an issue are findings |
| Completeness check | `*_total` in section 1 must equal the previous report's totals plus this period's events. Any difference is a finding (rows removed or back-dated) |
| Delivery and storage | The report contains pseudonymous personal data (internal IDs, operator handle, access history). Not by email attachment or chat; only through the access-restricted location agreed by JJ and the Technical Lead (not yet agreed); never in the repository |
| Proof of generation | The preparer records the report's SHA-256 in a report issue when it is generated |
| Proof of receipt and review | The reviewer records in the same issue: date received, the SHA-256 they computed (must match), review date, findings (each with a follow-up issue) and their sign-off |
| Retention | Reports and review records are kept and not deleted until PRIV-005 sets audit retention; then the same rule applies to them |

The report query. Read-only, one snapshot (`REPEATABLE READ READ ONLY`); run
with `psql -X -v period_start='<UTC timestamp>' -v period_end='<UTC timestamp>'`:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

-- 1. Boundaries and totals
SELECT current_database() AS database, now() AS generated_at,
       :'period_start'::timestamptz AS period_start,
       :'period_end'::timestamptz AS period_end,
       (SELECT count(*) FROM identity_events) AS identity_events_total,
       (SELECT count(*) FROM membership_events) AS membership_events_total,
       (SELECT count(*) FROM identity_events
         WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end') AS identity_events_in_period,
       (SELECT count(*) FROM membership_events
         WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end') AS membership_events_in_period;

-- 2. Identity and User events in the period
SELECT occurred_at, txid, event_type, user_id, identity_id, actor_kind, db_role, actor_reference, id
  FROM identity_events
 WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end'
 ORDER BY occurred_at, id;

-- 3. Membership events in the period
SELECT occurred_at, txid, event_type, company_id, membership_id, user_id, actor_kind, db_role, actor_reference, id
  FROM membership_events
 WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end'
 ORDER BY occurred_at, id;

-- 4. References to reconcile against the issue tracker
SELECT actor_reference, actor_kind, db_role, count(*) AS events,
       min(occurred_at) AS first_event, max(occurred_at) AS last_event
  FROM (SELECT actor_reference, actor_kind, db_role, occurred_at FROM identity_events
         WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end'
        UNION ALL
        SELECT actor_reference, actor_kind, db_role, occurred_at FROM membership_events
         WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end') AS events
 GROUP BY actor_reference, actor_kind, db_role
 ORDER BY actor_reference, actor_kind, db_role;

-- 5. Current access snapshot (internal IDs only)
SELECT m.company_id, m.id AS membership_id, m.user_id, u.status AS user_status,
       m.created_at, m.updated_at
  FROM memberships m JOIN users u ON u.id = m.user_id
 WHERE m.status = 'active'
 ORDER BY m.company_id, m.user_id;
SELECT status, count(*) AS users FROM users GROUP BY status ORDER BY status;
SELECT issuer, status, count(*) AS identities
  FROM user_identities GROUP BY issuer, status ORDER BY issuer, status;

COMMIT;
```
