.PHONY: install lint format-check typecheck test build check

install:
	pnpm install --frozen-lockfile
	cd apps/api && uv sync --frozen

lint:
	pnpm --filter @heroos/web lint
	cd apps/api && uv run ruff check .

format-check:
	cd apps/api && uv run ruff format --check .

typecheck:
	pnpm --filter @heroos/web typecheck
	cd apps/api && uv run mypy app scripts

test:
	pnpm --filter @heroos/web test
	cd apps/api && uv run pytest

build:
	pnpm --filter @heroos/web build

check: lint format-check typecheck test build

.PHONY: local-up local-down local-logs local-ps migrate migration-check db-runtime-role db-setup tenant-isolation-check

# Root .env (if present) supplies DATABASE_URL / MIGRATION_DATABASE_URL overrides.
API_ENV_FILE = $(if $(wildcard .env),--env-file ../../.env,)

local-up:
	docker compose up -d --wait db
	$(MAKE) db-setup
	docker compose up --build -d

local-down:
	docker compose down

local-logs:
	docker compose logs -f

local-ps:
	docker compose ps

# Database targets require the local Docker Compose `db` service.
# Migrations run as the migration/admin role (MIGRATION_DATABASE_URL).
migrate:
	cd apps/api && uv run $(API_ENV_FILE) alembic upgrade head

# Create/update the local RLS-restricted API login role (DATABASE_URL user).
# Local development only; idempotent; works on new and existing databases.
db-runtime-role:
	cd apps/api && uv run $(API_ENV_FILE) python -m scripts.bootstrap_runtime_role

db-setup: migrate db-runtime-role

migration-check:
	./scripts/verify-migrations.sh

# Real-PostgreSQL cross-tenant security suite on a disposable database.
tenant-isolation-check:
	./scripts/verify-tenant-isolation.sh

.PHONY: dev-token

# Local development bearer token for an existing users.identity_subject.
# Authentication only: grants no Company access by itself. Development only.
dev-token:
	@test -n "$(SUBJECT)" || { echo "usage: make dev-token SUBJECT=<identity-subject>" >&2; exit 2; }
	@cd apps/api && uv run $(API_ENV_FILE) python -m scripts.create_dev_token "$(SUBJECT)"
