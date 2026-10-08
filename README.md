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

## Local Database

M1 development uses PostgreSQL 16 from the local Docker Compose `db` service
(host port `5433`). Amazon RDS for PostgreSQL remains the target for deployed
environments and is provisioned separately; it is not required locally.

`DATABASE_URL` is the single connection setting (see `.env.example`).

Alembic migrations in `apps/api/migrations/versions/` are the only supported way
to change the schema. Committed migrations are immutable history; add a new
revision instead of editing an old one.

```bash
docker compose up -d db

# Apply migrations to the local development database
make migrate

# Generate a new revision after changing models (review it before applying)
cd apps/api && uv run alembic revision --autogenerate -m "describe change"

# Verify the full migration chain (base -> head -> base -> head) against a
# disposable `heroos_migration_test` database. The dev database is untouched.
make migration-check
```

`make check` runs source quality gates only and does not need a database.
