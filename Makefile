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

.PHONY: local-up local-down local-logs local-ps migrate migration-check db-runtime-role db-setup tenant-isolation-check backup-restore-check e2e-check

# Root .env (if present) supplies DATABASE_URL / MIGRATION_DATABASE_URL. There
# are no built-in database credentials: without .env (or exported variables)
# database targets stop with an error. Create it once with `make env-init`.
API_ENV_FILE = $(if $(wildcard .env),--env-file ../../.env,)

local-up: env-check
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

# Logical backup -> restore -> verify on disposable databases (never `heroos`).
backup-restore-check:
	./scripts/verify-backup-restore.sh

# Real web + API + PostgreSQL 16 + browser, signed in through a local OpenID
# Provider; everything disposable (own container on tmpfs, no Compose, no .env).
e2e-check:
	./scripts/verify-e2e.sh

.PHONY: privacy-decision-check

# Governance check of docs/privacy/decision-register.md and the JJ review packet
# (unique IDs, vocabularies, evidence for decided/confirmed/implemented states).
# The self-test first proves the checks reject bad registers.
privacy-decision-check:
	python3 scripts/check-privacy-decisions.py --self-test
	python3 scripts/check-privacy-decisions.py

.PHONY: dev-token

# Local development bearer token for a subject bound under urn:heroos:local-development.
# Authentication only: grants no Company access by itself. Development only.
dev-token:
	@test -n "$(SUBJECT)" || { echo "usage: make dev-token SUBJECT=<identity-subject>" >&2; exit 2; }
	@cd apps/api && uv run $(API_ENV_FILE) python -m scripts.create_dev_token "$(SUBJECT)"

.PHONY: env-init env-check env-rotate db-apply-credentials

# Database credentials (docs/operations/database-credentials.md). The root .env
# is the only place they live; no target prints a password or a database URL.

# Create .env from .env.example with generated passwords. Never overwrites.
env-init:
	@cd apps/api && uv run python -m scripts.db_credentials init

# Validate .env (0600, ignored, untracked, generated passwords, URLs agree).
env-check:
	@cd apps/api && uv run python -m scripts.db_credentials check

# Back up .env to BACKUP_DIR (0700, outside the repo) and generate new database
# passwords in .env. Does not touch the database. ROTATE_DEV_AUTH_SECRET=yes
# also replaces HEROOS_DEV_AUTH_SECRET.
env-rotate:
	@test -n "$(BACKUP_DIR)" || { echo "usage: make env-rotate BACKUP_DIR=<private dir outside the repo>" >&2; exit 2; }
	@cd apps/api && uv run python -m scripts.db_credentials rotate --backup-dir "$(abspath $(BACKUP_DIR))" \
		$(if $(filter yes,$(ROTATE_DEV_AUTH_SECRET)),--dev-auth-secret,)

# APPROVAL GATE: sets the heroos and heroos_app role passwords to the values in
# .env (SCRAM verifiers via the Compose db service), then verifies both logins.
db-apply-credentials:
	@test "$(CONFIRM)" = "yes" || { echo "db-apply-credentials changes role passwords; re-run with CONFIRM=yes after approval" >&2; exit 2; }
	@cd apps/api && uv run python -m scripts.db_credentials apply --confirm
