#!/usr/bin/env bash
# Run the real-PostgreSQL tenant isolation security suite.
#
# The pytest session (apps/api/tests/tenant_isolation/conftest.py) creates a
# disposable *_tenant_isolation_test database, applies all migrations as the
# migration/admin role, bootstraps a disposable RLS-restricted runtime login
# role (heroos_app_t_<hex>, never the shared heroos_app), runs the two-tenant
# tests as that role and drops both. This script adds a second, independent
# cleanup so neither outlives the run, and fails if the live heroos_app role
# changed.
#
# Uses only the local Docker Compose `db` service (CI starts the same service).
# Never touches the normal development database or the live heroos_app
# role. Credentials from the environment or the root .env (`make env-init`).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DB_USER="${POSTGRES_USER:-heroos}"
# shellcheck source=lib/credentials.sh
source "${REPO_ROOT}/scripts/lib/credentials.sh"
require_admin_password
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
  drop_disposable_runtime_role "${RUNTIME_LOGIN}" || { echo "WARNING: failed to drop ${RUNTIME_LOGIN}" >&2; status=1; }
  drop_disposable_operator_role "${OPERATOR_LOGIN}" || { echo "WARNING: failed to drop ${OPERATOR_LOGIN}" >&2; status=1; }
  assert_live_runtime_role_unchanged || status=1
  if [[ ${status} -eq 0 ]]; then
    log "Tenant isolation verification PASSED"
  else
    log "Tenant isolation verification FAILED (exit ${status})" >&2
  fi
  exit "${status}"
}

log "Checking local PostgreSQL service"
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres

new_disposable_runtime_role
new_disposable_operator_role
record_live_runtime_role
trap cleanup EXIT

log "Running tenant isolation suite against disposable database ${TEST_DB}"
cd apps/api
TENANT_TEST_ADMIN_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/postgres" \
TENANT_TEST_DATABASE="${TEST_DB}" \
TENANT_TEST_RUNTIME_ROLE="${RUNTIME_LOGIN}" \
TENANT_TEST_RUNTIME_PASSWORD="${RUNTIME_PASSWORD}" \
TENANT_TEST_OPERATOR_ROLE="${OPERATOR_LOGIN}" \
TENANT_TEST_OPERATOR_PASSWORD="${OPERATOR_PASSWORD}" \
TENANT_TEST_REQUIRED=1 \
  uv run pytest tests/tenant_isolation -v -p no:cacheprovider "$@"
