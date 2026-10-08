# HeroOS

HeroOS is a guided HR workflow platform that combines structured workflows,
deterministic Conditions, approved HR guidance and controlled AI assistance.

## V1 Scope

Initial workflows:

- Disciplinary
- Probation
- Recruitment

Initial jurisdictions:

- UAE Federal / MOHRE
- DIFC

ADGM is outside the V1 scope.

## Technology

- Next.js / TypeScript
- FastAPI / Python 3.12
- PostgreSQL
- AWS
- pnpm
- uv

## Repository Structure

```text
apps/
  web/        Next.js frontend
  api/        FastAPI backend

docs/
  architecture/
  decisions/
  privacy/

infrastructure/
  terraform/

.github/
  workflows/
```

## Local Database

M1 development uses PostgreSQL 16 from the local Docker Compose `db` service
(host port `5433`). Amazon RDS for PostgreSQL remains the target for deployed
environments and is provisioned separately; it is not required locally.

Two connection settings with different privileges (see `.env.example`):

- `DATABASE_URL`: the API runtime role `heroos_app`. It is not superuser, has no
  `BYPASSRLS` and owns no tables, so PostgreSQL Row-Level Security applies. The
  API refuses to start with a privileged role.
- `MIGRATION_DATABASE_URL`: the migration/admin role `heroos`, which owns the
  schema. Alembic uses it; the API never does.

Alembic migrations in `apps/api/migrations/versions/` are the only supported way
to change the schema. Committed migrations are immutable history; add a new
revision instead of editing an old one.

```bash
docker compose up -d db

# Apply migrations and create/update the local runtime login role
# (idempotent; works for new and existing Docker volumes)
make db-setup

# Generate a new revision after changing models (review it before applying)
cd apps/api && uv run alembic revision --autogenerate -m "describe change"

# Verify the full migration chain (base -> head -> base -> head) against a
# disposable `heroos_migration_test` database. The dev database is untouched.
make migration-check

# Real-PostgreSQL cross-tenant security suite (RLS, runtime role, pool leakage)
# against a disposable `heroos_tenant_isolation_test` database.
make tenant-isolation-check
```

`make check` runs source quality gates only and does not need a database.

Existing local `.env` files must be updated: `DATABASE_URL` now uses
`heroos_app`, and `MIGRATION_DATABASE_URL` is new (copy both from
`.env.example`). See
[docs/architecture/tenant-isolation.md](docs/architecture/tenant-isolation.md).

## Local Authentication

Protected API routes require a Bearer JWT, and access to a Company is granted
only through a HeroOS Membership. Production uses Amazon Cognito access tokens.
Live Cognito activation is planned for M3.

Locally, set `HEROOS_AUTH_PROVIDER=development` and `HEROOS_DEV_AUTH_SECRET`
(see `.env.example`), then issue a short-lived token for an existing
`users.identity_subject`:

```bash
make dev-token SUBJECT=<identity-subject>
```

`HEROOS_ENV` is required and has no default; the API will not start without it.
Docker Compose sets it for the `api` service. To run the API directly, load the
root `.env`: `cd apps/api && uv run --env-file ../../.env uvicorn app.main:app`.
Alembic needs only `MIGRATION_DATABASE_URL`.

The development provider is refused outside `HEROOS_ENV=development`. See
[docs/architecture/authentication.md](docs/architecture/authentication.md).
