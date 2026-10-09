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
Rotate in place (the data and volume are kept) with §4 Gates 4–7.

## 4. Phase B: rotating the VPS preview credentials

The preview runs in the deployment directory `~/Pictures/heroos-app` with the
retired committed credentials (§6). Every gate needs explicit approval before it
runs, and each one stops at the first failure.

**Why this order.** `.env` is rotated while the *old* code is still deployed:
the old `compose.yaml` ignores the new keys and running containers never re-read
`.env`, so nothing changes for the running preview. When the new
`compose.yaml` arrives (Gate 5), `.env` already has the keys it requires, so
`docker compose` stays usable throughout. The only service impact is Gate 6.

| Period | Running preview | `docker compose` in the deployment directory | Host DB tooling (`make migrate`, `db-runtime-role`, `db_recovery`) |
|---|---|---|---|
| Gates 0–3 | normal | normal | normal |
| Gate 4 → Gate 6 | normal | `ps`, `logs`, `exec` fine | **do not use**: `.env` already holds passwords the database does not accept yet |
| Gate 5 → Gate 6 | normal | **do not** `up`, `restart`, `make local-up`, `make db-setup`: they would start the API with the new password before the database has it | do not use |
| Gate 6: from the password change until the new API is healthy | API cannot open *new* database connections (open ones keep working); API down ~5–15 s while recreated; web and database stay up | fine | fine |

Never, at any gate: `docker compose down -v`, `docker volume rm`, migrations,
`make db-setup`, restoring into `heroos`, or reinstating retired credentials.

Shell variables used below:

```bash
B="$HOME/heroos-backups/<run-name>"        # private, 0700, outside the repository
LIVE="$HOME/Pictures/heroos-app"            # deployment directory
NEW="<separate checkout of the merged commit>"   # e.g. a git worktree; provides the new tooling for Gate 4
```

**Gate 0. Pre-flight (read-only).** Clean deployment checkout on the expected
commit, PR and CI green, `install -d -m 700 "$B"`, and a read-only snapshot of
the database saved as `"$B/baseline-before.txt"`: alembic revision, role
attributes and memberships, table owners and RLS flags, row counts, constraint
definitions, policies, grants, schema and function ACLs (definitions as
`md5()`, never passwords). Record container image IDs and start times, the
Docker volume list and the HTTP status of the API, web and HTTPS preview.

**Gate 1. Backup** (reads the database; writes only inside `$B`). Old code:

```bash
cd "$LIVE"
(cd apps/api && uv run --no-sync --env-file ../../.env python -m scripts.db_recovery \
  --pg-tools compose backup --database heroos --output "$B/heroos.dump")
(umask 077; docker compose exec -T db pg_dumpall -U heroos --roles-only --no-role-passwords > "$B/roles.sql")
grep -ciE 'password|scram|md5' "$B/roles.sql"        # must print 0
(cd "$B" && sha256sum heroos.dump roles.sql > SHA256SUMS)
```

The roles file deliberately has **no passwords**, so no restore can bring a
compromised credential back. Never take a roles backup without
`--no-role-passwords`.

**Gate 2. Verify the backup in a throwaway cluster** (no live change). Before
any live change, restore the archive into a separate Compose project
(`-p <name>`, its own compose file and `.env` from `db_credentials init --port
<free port>`), with the data directory on `tmpfs` and no volume:

1. `sha256sum --strict -c SHA256SUMS`;
2. guard: the resolved Compose project, port and storage are the throwaway ones,
   and the live `db` container ID is unchanged; export `COMPOSE_FILE` /
   `COMPOSE_PROJECT_NAME` for `db_recovery`, which calls `docker compose exec`;
3. `pg_restore --list`: one `TABLE DATA` entry per table and one `POLICY` per
   tenant table;
4. `bootstrap_runtime_role` (roles get *current* credentials, never backed-up
   ones), `CREATE DATABASE <restore db>`, `db_recovery restore`;
5. `scripts/lib/schema-assertions.sh` `assert_schema <restore db>`;
6. the Gate 0 snapshot of the restored copy equals the live baseline, compared
   **order-insensitively** (object IDs, and so catalog order, differ between
   clusters);
7. on the restored copy: revision is the single code head, `alembic check`
   reports no drift, the runtime role passes `check_runtime_role` and is denied
   `alembic_version`, `TRUNCATE`, `CREATE`, disabling RLS, dropping policies,
   `SET ROLE`, replacing `heroos_current_company_id()` and `row_security = off`;
   with probe rows, no tenant context sees nothing, tenant A sees only A,
   cannot update B and cannot insert another company;
8. always tear the throwaway project down (an exit trap) and confirm no
   containers, networks or volumes remain and the live snapshot is unchanged.

Do not continue with a backup that has not passed Gate 2.

**Gate 3. Merge** (GitHub only). Squash-merge after CI is green, wait for the
`main` CI run, then confirm `git diff --quiet <tested PR head> origin/main`.

**Gate 4. New credentials in the live `.env`, including `HEROOS_DEV_AUTH_SECRET`**
(old code still deployed; no service impact). Run the new tool from `$NEW`:

```bash
cd "$NEW/apps/api"
uv run python -m scripts.db_credentials --env-file "$LIVE/.env" rotate --backup-dir "$B" --dev-auth-secret
uv run python -m scripts.db_credentials --env-file "$LIVE/.env" check     # every line OK
```

Confirm by key name only that the five managed keys changed and no other key
did (compare against `"$B"/env.pre-rotation.*` with `hmac.compare_digest`,
printing names). The dev auth secret is not passed to any container, and the
preview API has no auth provider configured, so rotating it affects nothing
running.

**Gate 5. Deploy the code and pre-build the API image** (no restarts):

```bash
cd "$LIVE"
test -z "$(git status --porcelain)" && git pull --ff-only origin main
git diff --quiet <tested PR head> HEAD && echo "deployed tree == tested PR head"
(cd apps/api && uv sync --frozen)
docker compose config --quiet                 # never without --quiet: it prints secrets
make env-check
docker tag heroos-api:local heroos-api:pre-rotation   # image rollback point
docker compose build api                       # running containers are untouched
```

**Gate 6. Apply the passwords and recreate the API** (the only service impact;
run as one line so the API is recreated immediately):

```bash
cd "$LIVE"
make db-apply-credentials CONFIRM=yes && docker compose up -d --no-deps --force-recreate --wait --wait-timeout 120 api
```

`db-apply-credentials` validates `.env`, changes **only** the two passwords in
one transaction, proves role attributes and memberships unchanged and logs in
as both roles. `--no-deps` leaves `db` and `web` running.

**Gate 7. Verify (read-only).** `make env-check`; all containers healthy;
API `/health` 200, web 200, HTTPS preview 401 without credentials and working
through a browser login; the API container environment has only
`HEROOS_ENV` and `DATABASE_URL`; `pg_stat_activity` shows only `heroos_app`
from the API container; the database snapshot equals the Gate 0 baseline
(order-insensitive); `db` and `web` start times unchanged; previous passwords
are refused and current ones accepted (a login attempt per URL printing only
role and outcome); the runtime role passes `check_runtime_role` and cannot read
`alembic_version` or disable row security; container logs contain no current
or previous credential value (count only).

**Gate 8 (optional, separate approval). Recreate the `db` container.** The
`db` service definition changed (`POSTGRES_PASSWORD` now comes from `.env`), so
the next plain `docker compose up -d` recreates it. Do it deliberately, e.g.
together with other planned container changes: confirm the resolved volume is
`heroos_postgres_data -> /var/lib/postgresql/data`, run
`docker compose up -d --no-deps --wait db` (database restart of a few seconds;
the volume is reused and `POSTGRES_PASSWORD` is ignored for an initialised
data directory), then repeat the Gate 7 snapshot comparison.

**Gate 9 (optional, separate approval).** `make migration-check`,
`make tenant-isolation-check`, `make backup-restore-check` against the preview
cluster. They create and drop only `*_test` databases and `heroos_app_t_*`
roles and fail if `heroos_app` changes.

**Gate 10. Clean up** after a stable period: `shred -u "$B"/env.pre-rotation.*`
(retired credentials; never restore them, the tooling refuses them anyway),
`docker image rm heroos-api:pre-rotation`. Keep `heroos.dump`, `roles.sql` and
`SHA256SUMS` only as long as the retention decision allows (PRIV-018).

## 5. Rollback and fix-forward

| Gate | Failure | State | Action |
|---|---|---|---|
| 0–2 | any | nothing changed | stop; fix; re-run. Never continue with an unverified backup |
| 3 | `main` CI fails or trees differ | GitHub only | do not deploy; fix forward or revert on GitHub |
| 4 | rotate or check fails | old code, database untouched | `cp -p "$B"/env.pre-rotation.* "$LIVE/.env"` restores the exact previous state (the database still uses those passwords, so this is an abort, not a credential rollback) |
| 5 | pull, sync or build fails | containers untouched | `git -C "$LIVE" checkout --detach <previous commit>`, `docker tag heroos-api:pre-rotation heroos-api:local`, then the Gate 4 action |
| 6 | `apply` fails before commit | database unchanged; API not recreated (`&&`) | fix and retry, or the Gate 5 + Gate 4 actions |
| 6 | committed, login verification fails | database has new passwords; API cannot open new connections | `make env-check`, re-run `make db-apply-credentials CONFIRM=yes` (idempotent), then the recreate command |
| 6 | new API unhealthy: authentication | — | `docker compose logs --no-color --tail 100 api` (no secrets), re-run apply, recreate |
| 6 | new API unhealthy: application/image | — | `docker tag heroos-api:pre-rotation heroos-api:local && docker compose up -d --no-deps --force-recreate --wait api` (old image, new credentials: no credential rollback) |
| any | locked out | — | break-glass: `docker compose exec db psql -U heroos -d heroos` (socket trust inside the container; deliberate manual step) |
| after 6 | rotated credentials suspected wrong or leaked | — | rotate again: Gates 4, 6, 7 with a new `$B` |
| after 6 | code rollback requested | — | avoid: the pre-change `compose.yaml` hardcodes the retired password, and old-code `make db-setup` without `.env` would reinstate it. Fix forward; reverting is a deliberate decision to re-expose credentials and needs its own approval |
| any | data loss or corruption (not expected) | — | restore `heroos.dump` into a **new** database (`db_recovery restore --database heroos_restored_<date>`; it refuses `heroos`), validate ([Backup and Recovery §5](../architecture/backup-and-recovery.md)), cut over only with approval |

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
