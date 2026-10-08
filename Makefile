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

.PHONY: local-up local-down local-logs local-ps migrate migration-check

local-up:
	docker compose up --build -d

local-down:
	docker compose down

local-logs:
	docker compose logs -f

local-ps:
	docker compose ps

# Database targets require the local Docker Compose `db` service.
migrate:
	cd apps/api && uv run alembic upgrade head

migration-check:
	./scripts/verify-migrations.sh

.PHONY: dev-token

# Local development bearer token for an existing users.identity_subject.
# Authentication only: grants no Company access by itself. Development only.
dev-token:
	@test -n "$(SUBJECT)" || { echo "usage: make dev-token SUBJECT=<identity-subject>" >&2; exit 2; }
	@cd apps/api && uv run $(if $(wildcard .env),--env-file ../../.env,) python -m scripts.create_dev_token "$(SUBJECT)"
