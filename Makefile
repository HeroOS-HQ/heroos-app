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
	cd apps/api && uv run mypy app

test:
	pnpm --filter @heroos/web test
	cd apps/api && uv run pytest

build:
	pnpm --filter @heroos/web build

check: lint format-check typecheck test build