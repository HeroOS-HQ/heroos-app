# HeroOS Database Backup and Recovery

**Status:** Logical backup/restore procedure implemented (M1-07), proven on disposable PostgreSQL 16 databases locally and in CI. RDS backups/PITR deferred to M3\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security\
**Issue:** M1-07 — Establish secure storage, secrets, logging & backup foundation\
**Related:** [Tenant Isolation](tenant-isolation.md), [Production Security Gates](production-security-gates.md),
[Decision Register](../privacy/decision-register.md)

## 1. Scope and limits

This defines the V1 **logical** backup and restore of the HeroOS application
database with `pg_dump` / `pg_restore`, and the automated check that proves it.

A database dump is **not** a complete disaster-recovery solution:

- **Cluster-wide roles are not in the dump.** `heroos_app_runtime` (NOLOGIN
  privilege role), the API login role (`heroos_app` locally) and the
  migration/admin role exist at cluster level. The dump contains only the
  `GRANT`s that reference them.
- Cluster settings (`postgresql.conf`, `pg_hba.conf`), extensions installed
  outside the database, and other databases are not included.
- A logical dump is a point-in-time copy. It does not provide point-in-time
  recovery (PITR) between dumps.
- Object storage (private objects) is not in the database. Its recovery is the
  S3 versioning/replication decision for M3 (PRIV-019).

Production backups, PITR and their retention are M3 responsibilities (§7).

## 2. Requirements

| Requirement | Value |
| --- | --- |
| PostgreSQL server | 16 (Compose `postgres:16-alpine` locally and in CI; RDS for PostgreSQL 16 at M3) |
| Client tools | `pg_dump` / `pg_restore` with a major version ≥ the server. `--pg-tools compose` uses the 16.x client inside the Compose `db` service |
| Backup/restore role | the **migration/admin role** (`MIGRATION_DATABASE_URL`). It owns the schema, so `pg_dump` reads every row (owners are not subject to non-forced RLS) |
| Never | the API runtime role (`DATABASE_URL`). It is subject to RLS and would produce an empty or partial dump. The tool refuses it |

## 3. Tooling

`apps/api/scripts/db_recovery.py` (not shipped in the API image):

```bash
cd apps/api
# Backup (read-only): custom-format archive, 0600, in an existing private directory.
uv run python -m scripts.db_recovery [--pg-tools compose] backup \
    --database heroos --output /secure/private-dir/heroos-YYYYMMDD.dump

# Restore: only into an existing, empty, non-protected database.
uv run python -m scripts.db_recovery [--pg-tools compose] restore \
    --database heroos_restored_YYYYMMDD --input /secure/private-dir/heroos-YYYYMMDD.dump
```

**Credentials.** The tool reads `MIGRATION_DATABASE_URL` (a `SecretStr`) and
passes host, port, user and password to `pg_dump` / `pg_restore` only as
`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` and `PGDATABASE` in the child
process environment, with `--no-password` so the tools never prompt. The
password is never a command-line argument. Compose mode forwards the variables
by name (`docker compose exec -e PGPASSWORD …`) and connects to `db:5432` over
the Compose network, so scram-sha-256 password authentication is actually
exercised rather than loopback trust. Tool error output is redacted before it
is shown. Nothing prints `DATABASE_URL` or the password.

**Archive handling.** Archives contain the full database and are treated as
sensitive:

- written only into an **existing private directory** (no group or other
  permissions, owned by the operator, not a symlink) **outside the repository**;
- created with `O_EXCL | O_NOFOLLOW` and mode `0600` (set explicitly), so an
  existing archive is never overwritten;
- validated as a custom-format archive (`PGDMP` header). A failed or partial
  backup is deleted;
- filenames carry the database name and date only, never credentials;
- never written under a web-served directory, never committed (`.gitignore`
  ignores `*.dump`, `*.pgdump`, `*.backup` and `backups/` as a second guard).

**Restore safety.** `restore` refuses:

- protected databases: `heroos`, `postgres`, `template0`, `template1`,
  `rdsadmin`, `azure_maintenance`, and the databases named in `DATABASE_URL` /
  `MIGRATION_DATABASE_URL`;
- production-like names (`prod`, `production`, `live`, `primary` as a name
  segment);
- a target that does not exist, or that is **not empty**;
- a missing, non-regular, symlinked, non-custom-format or broadly readable
  archive;
- a cluster where `heroos_app_runtime` does not exist (roles must be
  bootstrapped first).

It restores with `--single-transaction --exit-on-error`, so the restore is
all-or-nothing, and `--no-owner`, so the restoring migration/admin role owns
every object (the runtime role must own nothing). Privileges (`GRANT`s), RLS
settings, policies and the tenant context function come from the archive.

Recovery never overwrites the live database. Restore into a new database,
verify it (§5), then switch connection configuration deliberately. In-place
recovery of a live database is not an automated mode.

## 4. Recovery procedure (logical restore)

1. **Prepare the cluster.** Use PostgreSQL 16. Create the database owned by the
   migration/admin role: `CREATE DATABASE heroos_restored_YYYYMMDD OWNER <admin role>`.
2. **Bootstrap cluster roles before restoring**, in this order:
   1. the migration/admin role (exists on the cluster, or is the RDS master or
      a dedicated owner role);
   2. `heroos_app_runtime`: `NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`.
      Locally, `make db-runtime-role` (`scripts.bootstrap_runtime_role`) creates
      it;
   3. the API login role (`heroos_app` locally; secret-managed in deployed
      environments) as a member of `heroos_app_runtime`, with the same negative
      attributes.
3. **Restore** with `scripts.db_recovery restore` as the migration/admin role.
4. **Validate** before any traffic (§5).
5. **Cut over** by pointing `DATABASE_URL` / `MIGRATION_DATABASE_URL` at the
   restored database through the secret store. The API startup guard
   (`verify_runtime_role`) refuses a runtime role that is superuser,
   `BYPASSRLS`, `CREATEROLE` or a table owner.
6. **Re-apply deletions** made after the backup was taken, according to the
   approved policy (PRIV-018). Until that decision exists, a restored backup
   must not be put into service without engineering and JJ sign-off.

## 5. Post-restore validation

`make backup-restore-check` automates every step below. Run the same checks
manually after a real restore:

- `scripts/lib/schema-assertions.sh` (`assert_schema <db>`). These are the same
  catalog assertions `make migration-check` uses: expected tables and
  constraints, the composite tenant-safe foreign key, RLS enabled on exactly
  the five tenant tables, one permissive `FOR ALL` `tenant_isolation` policy per
  table, and `heroos_app_runtime` as NOLOGIN without SUPERUSER/BYPASSRLS;
- `alembic current` equals `alembic heads`, and `alembic check` reports no
  drift;
- the runtime role passes the startup guard, sees no rows without a tenant
  context, sees only its Company's rows with one, and cannot write another
  Company's rows (`42501`).

## 6. Automated verification: `make backup-restore-check`

`scripts/verify-backup-restore.sh` with `apps/api/tests/recovery/`. It runs
locally and in the CI **Backup & Restore** job against the Compose PostgreSQL
16 service. It uses no AWS and no production data.

```text
create disposable heroos_backup_source_test  (name must match *_backup_source_test)
  -> alembic upgrade head (admin role) -> bootstrap runtime role
  -> seed deterministic synthetic data (2 Companies, every table)
  -> db_recovery backup -> assert workdir 0700, archive 0600
  -> create empty heroos_backup_restore_test (must match *_backup_restore_test)
  -> db_recovery restore
  -> assert_schema, alembic head, alembic check
  -> tests/recovery (24 tests): rows identical to source; data equals the
     synthetic dataset; catalog identical to source (tables + RLS flags,
     columns, constraints, indexes, policies, functions, runtime grants,
     alembic_version); revision is Alembic head; exact policies; tenant
     context function; admin owns everything; exact runtime grants (no
     TRUNCATE); runtime role passes the startup guard, sees nothing without
     context, is isolated per Company, cannot write cross-tenant
  -> restore refusals: non-empty target, heroos, postgres, template1, heroos_production
  -> trap (always, success or failure): drop both databases, delete the
     workdir and archive; the run FAILS if either survives
```

The private workdir is created with `mktemp -d` under `$RUNNER_TEMP` / `$TMPDIR`
(outside the repository) with `umask 077`. The normal `heroos` development
database is never created, dropped, restored or read.

Mutation checks (M1-07). Each of these made the check fail: a `0644` archive,
removing workdir cleanup, accepting the runtime role, restoring with
`--no-privileges`, and disabling RLS on one restored table.

## 7. Production (M3): not active

- Amazon RDS for PostgreSQL 16 with **automated backups** and **PITR**. The
  backup retention window is not decided (PRIV-007). RPO and RTO are not decided
  (PRIV-017).
- RDS snapshots and automated backups **encrypted at rest** with KMS (enabled at
  instance creation; it cannot be added later). Cross-region or cross-account
  copies only if approved (PRIV-013).
- Restore drills on a schedule, using this document's validation (§5) against
  the restored instance. Roles are recreated per §4 because RDS restores
  instance-level roles with the instance, but a logical restore into a new
  cluster does not.
- Logical dumps in production, if used at all, are stored only in an encrypted,
  access-controlled location with an approved retention period. Never on
  developer machines.
- Backup failure visibility: RDS event notifications and alarms (chosen at M3).
- Deletion requests versus existing backups, and treatment of restored backups:
  PRIV-018.
