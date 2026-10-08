#!/usr/bin/env bash
# Run the real-PostgreSQL tenant isolation security suite.
#
# The pytest session (apps/api/tests/tenant_isolation/conftest.py) creates a
# disposable *_tenant_isolation_test database, applies all migrations as the
# migration/admin role, bootstraps the RLS-restricted runtime role, runs the
# two-tenant tests as that role and drops the database. This script adds a
# second, independent cleanup so the database never outlives the run.
#
# Uses only the local Docker Compose `db` service (CI starts the same service).
# Never touches the normal development database. Local credentials only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DB_USER="${POSTGRES_USER:-heroos}"
DB_PASSWORD="${POSTGRES_PASSWORD:-heroos_local}"
DB_HOST="${TENANT_TEST_DB_HOST:-localhost}"
DB_PORT="${TENANT_TEST_DB_PORT:-5433}"
TEST_DB="${TENANT_TEST_DATABASE:-heroos_tenant_isolation_test}"

# Safety guard: only ever operate on a clearly disposable database.
if [[ ! "${TEST_DB}" =~ ^[a-z0-9_]+_tenant_isolation_test$ ]]; then
  echo "Refusing to run: '${TEST_DB}' must match *_tenant_isolation_test." >&2
  exit 1
fi

log() {
  printf '\n==> %s\n' "$*"
}

drop_test_db() {
  docker compose exec -T -e PGOPTIONS=--client-min-messages=warning db \
    psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres -qtAc \
    "DROP DATABASE IF EXISTS ${TEST_DB} WITH (FORCE);" >/dev/null
}

cleanup() {
  local status=$?
  drop_test_db || echo "WARNING: failed to drop ${TEST_DB}" >&2
  if [[ ${status} -eq 0 ]]; then
    log "Tenant isolation verification PASSED"
  else
    log "Tenant isolation verification FAILED (exit ${status})" >&2
  fi
}

log "Checking local PostgreSQL service"
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres

trap cleanup EXIT

log "Running tenant isolation suite against disposable database ${TEST_DB}"
cd apps/api
TENANT_TEST_ADMIN_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/postgres" \
TENANT_TEST_DATABASE="${TEST_DB}" \
TENANT_TEST_REQUIRED=1 \
  uv run pytest tests/tenant_isolation -v -p no:cacheprovider "$@"
