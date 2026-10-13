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
| Identity operator login (`heroos_op_<handle>`, one per person) | that operator's workstation only (`~/.pgpass`, 0600) | the API, Render, Vercel or CI. The API refuses to start with it |
| Migration owner | Technical Lead, for Alembic only | the API or the operator CLI (both refuse it) |

Handles should be opaque (`heroos_op_01`); the handle-to-person mapping is kept
in the Technical Lead's operational records. This is pending JJ's decision
(ADR-008).

### Creating an operator login

- **Local development / CI:** with `MIGRATION_DATABASE_URL` and
  `HEROOS_OPERATOR_DATABASE_URL` (a `heroos_op_*` login and a generated
  password) in the environment,
  `cd apps/api && uv run python -m scripts.bootstrap_runtime_role --operator`.
  It refuses non-local hosts.
- **Deployed database (approval required):** as the migration owner, after B1b:

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
  one, and records it with your login in the audit tables.
- Output is JSON with an outcome (`created`, `updated`, `unchanged`, `refused`)
  and internal IDs; subjects are never printed. Exit codes: 0 done, 2 usage,
  3 pre-flight refused, 4 operation refused, 5 database error.
- Suspension or revocation takes effect on the API's next request. Also disable
  the account at the identity provider, so it cannot obtain new tokens.

## 3. Deploying the identity migrations (approval required)

Order, for a database that already has users:

1. Confirm the API host does **not** auto-deploy from `main`.
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
   anyone (fail closed). Create operator logins (§1).

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
  Controls: the owner credential is held by the Technical Lead for Alembic only,
  never by a service; shipping audit events to separate immutable storage is M5
  work. The disposable test suites use the superuser-only replica switch to
  reset their own databases.

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
