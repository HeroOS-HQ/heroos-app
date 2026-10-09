# HeroOS Database Credentials: Local and Preview Environments

**Status:** Phase A implemented (tooling, fail-closed configuration, tests). Rotation of the VPS preview credentials (Phase B) awaits approval\
**Owner:** Technical Lead\
**Scope:** Local development, CI and the temporary VPS preview (Docker Compose). Deployed AWS environments use Secrets Manager (M5)\
**Related:** [Tenant Isolation](../architecture/tenant-isolation.md), [Backup and Recovery](../architecture/backup-and-recovery.md),
[Production Security Gates](../architecture/production-security-gates.md), [Security Boundaries §7](../architecture/security-boundaries.md#7-secrets-and-configuration)

## 1. Model

| Credential | Role | Lives in | Used by |
|---|---|---|---|
| `HEROOS_DB_ADMIN_PASSWORD` | `heroos` (migration/admin, superuser, owns the schema) | root `.env` | Compose `POSTGRES_PASSWORD` (empty-volume initialisation only), verification scripts |
| `MIGRATION_DATABASE_URL` | `heroos` | root `.env` | Alembic, `db-runtime-role`, `db_recovery` (host tooling). Never the API |
| `HEROOS_DB_APP_PASSWORD` | `heroos_app` (API runtime login, RLS-restricted) | root `.env` | Compose api `DATABASE_URL` |
| `DATABASE_URL` | `heroos_app` | root `.env` | Host tooling, API run outside Compose |
| `HEROOS_DEV_AUTH_SECRET` | — (signs local dev tokens) | root `.env` | `make dev-token`, development auth provider |

- The root `.env` is the **only** place these values live. It is mode 0600,
  ignored by Git (`.gitignore`) and by Docker builds (`.dockerignore`).
- **No defaults anywhere.** `compose.yaml` uses required interpolation
  (`${HEROOS_DB_APP_PASSWORD:?…}`), `DatabaseSettings` has no default URL, the
  API refuses to start without `DATABASE_URL`, Alembic refuses to run without
  `MIGRATION_DATABASE_URL`, and the verification scripts stop without
  `HEROOS_DB_ADMIN_PASSWORD`. Nothing silently falls back to a known password.
- **Generated, never typed.** Passwords are 32 random bytes as 64 lowercase hex
  characters (URL-, shell- and dotenv-safe). Every tool that sets a password
  refuses anything else, so a placeholder, a hand-typed password or one of the
  retired committed development defaults can never be (re)applied, including
  from an old `.env` backup.
- **Hashed before it leaves the host.** `db-runtime-role` and
  `db-apply-credentials` send `ALTER ROLE … PASSWORD 'SCRAM-SHA-256$…'`
  verifiers computed client-side (`apps/api/scripts/scram.py`). Plaintext never
  appears in SQL text, so it cannot reach the PostgreSQL log
  (`log_min_error_statement`) or a psql error echo. Tool errors redact verifiers.
- **Never printed.** No command prints a password, a verifier or a full database
  URL. `make env-check` reports key names and OK/FAIL only.
- **Tests never touch `heroos_app`.** Roles are cluster-wide. The tenant
  isolation and backup/restore suites create a disposable login role
  (`heroos_app_t_<8 hex>`, random password) per run and drop it afterwards;
  the fixtures refuse `heroos_app`, `bootstrap_runtime_role` refuses to manage
  `heroos_app` from a `*_test` database, and the scripts fail if the
  `heroos_app` credential or attributes changed during the run.

The API container receives only `HEROOS_ENV` and `DATABASE_URL` (runtime role).
It never receives the admin credential, and its startup guard
(`verify_runtime_role`) refuses a superuser, `BYPASSRLS`, `CREATEROLE` or
table-owning role.

## 2. Commands

| Command | Effect | Touches the database |
|---|---|---|
| `make env-init` | Create `.env` from `.env.example` with generated values. Never overwrites | No |
| `make env-check` | Validate `.env`: 0600 and owned by you, Git-ignored and untracked, generated passwords, admin ≠ runtime, URLs match the passwords, roles `heroos`/`heroos_app`, local host, database `heroos` | No |
| `make env-rotate BACKUP_DIR=<dir>` | Copy `.env` to `<dir>/env.pre-rotation.<UTC>` (0600; `<dir>` must be 0700 and outside the repo), then generate new database passwords and URLs in `.env`. `ROTATE_DEV_AUTH_SECRET=yes` also replaces the dev auth secret | No |
| `make db-apply-credentials CONFIRM=yes` | **Approval gate.** Run `env-check`; set the `heroos` and `heroos_app` passwords to the `.env` values in one transaction through the Compose `db` service; prove role attributes and memberships are unchanged; log in over TCP with both new passwords and re-run the runtime-role guard | Passwords only |
| `make db-runtime-role` | Create/update `heroos_app` from `DATABASE_URL` (SCRAM verifier) | Runtime role |

`db-apply-credentials` connects through the `db` container's local socket,
which the official PostgreSQL image trusts. It therefore works whatever the
current passwords are and cannot lock the admin out. The same socket is the
break-glass path (§5). Anyone who can run `docker` on the host is effectively
root there, so this adds no exposure on a single-operator host.

### Things that reveal secrets: avoid them

- `docker compose config` prints the resolved configuration, **including
  passwords**. Use `docker compose config --quiet` to validate only.
- `docker inspect <api container>` shows its environment, including
  `DATABASE_URL`.
- `cat .env`, `env`, `set -x` in scripts, or pasting `.env` into tickets, chat
  or AI tools.

## 3. Developer and CI setup

```bash
make env-init     # once
make env-check
make local-up     # runs env-check first
```

CI generates fresh credentials per run (`make env-init`), masks them with
`::add-mask::`, validates them with `make env-check`, then starts the Compose
`db` service. No repository secret is needed and nothing is committed.

A `.env` from before this change has no `HEROOS_DB_*` keys and holds the retired
committed passwords. `env-check` fails on it and Compose refuses to start.
Rotate in place (the data and volume are kept) with §4 steps 4–6.

## 4. Phase B: rotating the VPS preview credentials

The preview runs in the deployment directory `~/Pictures/heroos-app` with the
retired committed credentials (§6). Each **gate** needs explicit approval before
it runs. The steps are ordered so the running containers keep serving until
step 6, and the database is only changed in step 5.

> Until step 4 has run, the deployment directory's `.env` has no
> `HEROOS_DB_*` keys. After the new code is checked out there (step 3), every
> `docker compose` command (including `ps`, `logs` and `exec`) refuses to run
> until step 4. The running containers are not affected.

**1. Pre-flight (read-only).** On the current code:

```bash
cd ~/Pictures/heroos-app
docker compose ps
docker compose exec -T db psql -X -U heroos -d heroos -qtA -c \
  "SELECT version_num FROM alembic_version"
docker compose exec -T db psql -X -U heroos -d heroos -qtA -c \
  "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname LIKE 'heroos%' ORDER BY 1"
docker compose exec -T db psql -X -U heroos -d heroos -qtA -c \
  "SELECT relname, pg_get_userbyid(relowner), relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' ORDER BY 1"
for t in companies users memberships company_blueprints case_subjects cases; do
  docker compose exec -T db psql -X -U heroos -d heroos -qtA -c "SELECT '$t', count(*) FROM $t"
done
```

Save the output for comparison in step 7. It contains no secrets.

**2. Backup: GATE G1** (writes a data dump outside the repository). On the
current code:

```bash
B="$HOME/heroos-backups/$(date -u +%Y%m%dT%H%M%SZ)-pre-rotation"
install -d -m 700 "$B"
(cd apps/api && uv run --env-file ../../.env python -m scripts.db_recovery \
  --pg-tools compose backup --database heroos --output "$B/heroos.dump")
docker compose exec -T db pg_restore --list < "$B/heroos.dump" | grep -c 'TABLE DATA'
(umask 077; docker compose exec -T db pg_dumpall -U heroos --roles-only --no-role-passwords > "$B/roles.sql")
grep -ciE 'password|scram' "$B/roles.sql"    # must print 0
```

The roles file deliberately has **no passwords** (`--no-role-passwords`), so no
restore can bring a compromised credential back. Do not take a roles backup
without that flag. Optional, and a separate approval: prove the dump restores
into a disposable database (`scripts.db_recovery restore --database
heroos_prerotation_restore_test`, then drop it). The tool refuses `heroos`.

**3. Deploy the code: GATE G2** (merge the PR, then update the deployment
directory). Running containers are unaffected.

```bash
git fetch origin && git checkout main && git pull --ff-only
```

**4. Generate new credentials: GATE G3** (modifies the live `.env`; the
database is untouched).

```bash
make env-rotate BACKUP_DIR="$B"            # add ROTATE_DEV_AUTH_SECRET=yes to also rotate it
make env-check                              # every line must be OK (git SKIP is fine)
```

**5. Apply to the database: GATE G4** (two `ALTER ROLE … PASSWORD` statements;
nothing else changes).

```bash
make db-apply-credentials CONFIRM=yes
```

From here until step 6, the running API keeps its existing pooled connections,
but any new connection it opens fails, because its container still has the old
password. Run step 6 immediately.

**6. Recreate only the API container: GATE G5** (short API interruption).

```bash
docker compose up -d --no-deps --force-recreate api
```

`--no-deps` leaves `db` and `web` alone. `POSTGRES_PASSWORD` changed in `.env`,
so a later plain `docker compose up -d` will also recreate the `db` *container*.
That is a short database restart; the named volume and its data are kept, and
`POSTGRES_PASSWORD` is ignored for an initialised volume. Optionally do it now
in the same window (GATE G6): `docker compose up -d --no-deps db`. Never use
`down -v` or remove `heroos-local_heroos_postgres_data`.

**7. Verify (read-only).**

```bash
make env-check
docker compose ps                                     # api healthy
curl -fsS http://127.0.0.1:8001/health                 # {"status":"ok"}
docker compose exec -T db psql -X -U heroos -d heroos -qtA -c \
  "SELECT usename, client_addr, count(*) FROM pg_stat_activity WHERE datname = 'heroos' AND client_addr IS NOT NULL GROUP BY 1, 2"
                                                       # only heroos_app from the api container
# Repeat the step 1 queries: roles, ownership, RLS, alembic head, row counts unchanged.
# Credential values in container logs (patterns via a pipe, never argv): must print 0
docker compose logs --no-color api db | grep -c -F -f <(grep -E '^HEROOS_DB_(ADMIN|APP)_PASSWORD=' .env | cut -d= -f2-)
```

Old passwords must be refused. Check with the saved `env.pre-rotation.*` file
without printing it, for example with a short psycopg login attempt for each
URL in that file, which must fail with "password authentication failed". Then
check the preview end to end through Caddy.

Optional, a separate approval (GATE G7): `make migration-check`,
`make tenant-isolation-check` and `make backup-restore-check` against the
preview cluster. They use only disposable `*_test` databases and disposable
`heroos_app_t_*` roles, and fail if `heroos_app` changes.

**8. Clean up.** Once verified, delete `"$B"/env.pre-rotation.*`
(`shred -u`). It holds the retired, publicly known credentials and must never be
restored; the tooling would refuse it anyway. Keep `heroos.dump` and
`roles.sql` (0600, in a 0700 directory) only as long as the retention decision
allows (PRIV-018), then delete them.

## 5. Rollback

| Situation | Action |
|---|---|
| Stopped before step 5 (database untouched) | Nothing to undo in the database or the containers. To return to the previous state completely: `cp -p "$B"/env.pre-rotation.* .env` and check out the previous commit. |
| Step 5 or 6 failed, or the API does not come back | **Roll forward; do not restore the old credentials.** `make env-check`, then re-run `make db-apply-credentials CONFIRM=yes` (idempotent: it re-syncs both roles to `.env`), then step 6. `docker compose logs api` contains no secrets. |
| Rotated credentials suspected wrong or leaked | Rotate again: §4 steps 4–7 with a new `BACKUP_DIR`. |
| A previous *generated* `.env` must be reinstated | `cp -p <backup> .env`, `make db-apply-credentials CONFIRM=yes`, step 6. Works only for generated values; the retired defaults are refused. |
| Locked out / break-glass | `docker compose exec db psql -U heroos -d heroos` (socket trust inside the container, no password). This is an explicit manual action, not an automatic fallback. |
| Code must be rolled back after rotation | Avoid it. The pre-change `compose.yaml` hardcodes the retired password: the API would fail to start, and an old-code `make db-setup` without `.env` would put the compromised password back. Fix forward. Reverting the code is a deliberate decision to re-expose credentials and needs its own approval. |
| Data loss or corruption (not expected: rotation changes no data) | Restore `heroos.dump` into a **new** database (`scripts.db_recovery restore --database heroos_restored_<date>`; the tool refuses `heroos`), validate it ([Backup and Recovery §5](../architecture/backup-and-recovery.md)), and cut over only with approval. Roles get the current credentials, never ones from a backup. |

## 6. History of the retired development credentials

Before this change, the local development passwords for `heroos` and
`heroos_app` and the development auth signing secret were committed in
`compose.yaml`, `.env.example`, `apps/api/app/core/database_settings.py`, the
verification scripts and test fixtures. They have been in Git history since
the first database commits, on `main` and every feature branch.

- The repository is private with no forks. The values are readable by anyone
  with repository access, by GitHub, by every clone, and by tools that have read
  the repository. They are also guessable. **Treat them as public.**
- The VPS preview used exactly these values until Phase B. PostgreSQL is bound to
  127.0.0.1 and reachable otherwise only on the Compose network, so using them
  required shell access on the host or code execution / SSRF inside the `api` or
  `web` container.
- The preview API container receives no `HEROOS_AUTH_PROVIDER`, so it accepts
  no development tokens and the committed dev auth secret could not be used
  against it. Rotate it anyway (`ROTATE_DEV_AUTH_SECRET=yes`) before the
  development provider is ever enabled there.
- History is **not** rewritten. A rewrite would not reach existing clones and
  would disrupt collaborators. Once rotated, the values authenticate nothing.
  The managed-password policy guarantees they can never be applied again.
- Regression tests (`apps/api/tests/test_credential_hygiene.py`) fail if a
  literal credentialed database URL or a password default reappears in any
  tracked or new file, or if Compose or CI stop failing closed.
