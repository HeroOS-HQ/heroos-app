#!/usr/bin/env bash
# Verify the full Alembic migration chain against a disposable, empty local
# PostgreSQL database: base -> head, schema and Row-Level Security assertions,
# base, head again. Alembic runs as the migration/admin role.
#
# Uses only the local Docker Compose `db` service. Never touches the normal
# development database. Local development credentials only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DB_USER="${POSTGRES_USER:-heroos}"
DB_PASSWORD="${POSTGRES_PASSWORD:-heroos_local}"
DB_HOST="${MIGRATION_TEST_DB_HOST:-localhost}"
DB_PORT="${MIGRATION_TEST_DB_PORT:-5433}"
TEST_DB="${MIGRATION_TEST_DB:-heroos_migration_test}"

# Safety guard: only ever operate on a clearly disposable database.
if [[ ! "${TEST_DB}" =~ ^[a-z0-9_]+_migration_test$ ]]; then
  echo "Refusing to run: '${TEST_DB}' must match *_migration_test." >&2
  exit 1
fi

TEST_DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${TEST_DB}"

EXPECTED_TABLES=(
  alembic_version
  case_subjects
  cases
  companies
  company_blueprints
  memberships
  users
)

EXPECTED_CONSTRAINTS=(
  companies_pkey
  users_pkey
  users_identity_subject_key
  memberships_pkey
  memberships_company_id_fkey
  memberships_user_id_fkey
  uq_memberships_company_user
  company_blueprints_pkey
  company_blueprints_company_id_fkey
  uq_company_blueprints_company_id
  ck_company_blueprints_employee_count_nonnegative
  case_subjects_pkey
  case_subjects_company_id_fkey
  uq_case_subjects_company_id_id
  cases_pkey
  cases_company_id_fkey
  uq_cases_company_id_id
  fk_cases_company_id_subject_id_case_subjects
)

# Tenant-owned tables protected by Row-Level Security. `users` is a global
# identity table and deliberately has no tenant policy.
RLS_TABLES=(
  case_subjects
  cases
  companies
  company_blueprints
  memberships
)
RUNTIME_ROLE=heroos_app_runtime

log() {
  printf '\n==> %s\n' "$*"
}

psql_admin() {
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres -qtAc "$1"
}

psql_test() {
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${TEST_DB}" -qtAc "$1"
}

alembic() {
  (cd apps/api && MIGRATION_DATABASE_URL="${TEST_DATABASE_URL}" uv run alembic "$@")
}

drop_test_db() {
  psql_admin "DROP DATABASE IF EXISTS ${TEST_DB} WITH (FORCE);" >/dev/null
}

cleanup() {
  local status=$?
  log "Dropping disposable database ${TEST_DB}"
  drop_test_db || echo "WARNING: failed to drop ${TEST_DB}" >&2
  if [[ ${status} -eq 0 ]]; then
    log "Migration verification PASSED"
  else
    log "Migration verification FAILED (exit ${status})" >&2
  fi
}

assert_schema() {
  local actual expected missing=()

  actual="$(psql_test "SELECT string_agg(table_name, ' ' ORDER BY table_name)
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")"
  expected="${EXPECTED_TABLES[*]}"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Unexpected tables." >&2
    echo "  expected: ${expected}" >&2
    echo "  actual:   ${actual}" >&2
    return 1
  fi
  echo "Tables OK: ${actual}"

  for name in "${EXPECTED_CONSTRAINTS[@]}"; do
    if [[ "$(psql_test "SELECT count(*) FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'public' AND c.conname = '${name}';")" != "1" ]]; then
      missing+=("${name}")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing constraints: ${missing[*]}" >&2
    return 1
  fi
  echo "Constraints OK: ${#EXPECTED_CONSTRAINTS[@]} expected constraints present"

  # The cross-tenant guard must null only subject_id, never the tenant column.
  if [[ "$(psql_test "SELECT pg_get_constraintdef(oid) FROM pg_constraint
      WHERE conname = 'fk_cases_company_id_subject_id_case_subjects';")" \
      != "FOREIGN KEY (company_id, subject_id) REFERENCES case_subjects(company_id, id) ON DELETE SET NULL (subject_id)" ]]; then
    echo "Composite case subject foreign key has an unexpected definition." >&2
    return 1
  fi
  echo "Composite tenant-safe case -> case_subject FK OK"

  actual="$(psql_test "SELECT string_agg(relname, ' ' ORDER BY relname) FROM pg_class
    WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relrowsecurity;")"
  expected="${RLS_TABLES[*]}"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Unexpected Row-Level Security tables." >&2
    echo "  expected: ${expected}" >&2
    echo "  actual:   ${actual}" >&2
    return 1
  fi
  # Exactly one permissive FOR ALL policy per table, with USING and WITH CHECK.
  if [[ "$(psql_test "SELECT count(*) FROM pg_policies WHERE schemaname = 'public'
      AND policyname = 'tenant_isolation' AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
      AND qual LIKE '%heroos_current_company_id()%'
      AND with_check LIKE '%heroos_current_company_id()%';")" != "${#RLS_TABLES[@]}" \
      || "$(psql_test "SELECT count(*) FROM pg_policies WHERE schemaname = 'public';")" \
      != "${#RLS_TABLES[@]}" ]]; then
    echo "Unexpected tenant isolation policies." >&2
    psql_test "SELECT tablename, policyname, permissive, cmd, qual, with_check
      FROM pg_policies WHERE schemaname = 'public';" >&2
    return 1
  fi
  echo "RLS OK: ${actual} (one tenant_isolation policy each)"

  if [[ "$(psql_test "SELECT count(*) FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}'
      AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcanlogin;")" != "1" ]]; then
    echo "Runtime role ${RUNTIME_ROLE} is missing or privileged." >&2
    return 1
  fi
  echo "Runtime privilege role ${RUNTIME_ROLE} OK (NOLOGIN, no SUPERUSER, no BYPASSRLS)"
}

assert_at_head() {
  local current heads
  current="$(alembic current 2>/dev/null | awk '{print $1}')"
  heads="$(alembic heads 2>/dev/null | awk '{print $1}')"
  if [[ -z "${current}" || "${current}" != "${heads}" ]]; then
    echo "alembic current (${current:-none}) is not head (${heads})." >&2
    return 1
  fi
  echo "alembic current is head: ${current}"
}

log "Checking local PostgreSQL service"
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T db pg_isready -U "${DB_USER}" -d postgres

log "Checking Alembic has a single head"
if [[ "$(alembic heads 2>/dev/null | wc -l)" -ne 1 ]]; then
  echo "Expected exactly one Alembic head." >&2
  alembic heads >&2
  exit 1
fi

log "Creating empty disposable database ${TEST_DB}"
drop_test_db
trap cleanup EXIT
psql_admin "CREATE DATABASE ${TEST_DB};" >/dev/null

log "Upgrading base -> head"
alembic upgrade head
assert_at_head
assert_schema

log "Checking ORM models match the migrated schema"
alembic check

log "Downgrading head -> base"
alembic downgrade base
remaining="$(psql_test "SELECT count(*) FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name <> 'alembic_version';")"
if [[ "${remaining}" != "0" ]]; then
  echo "Downgrade to base left ${remaining} application tables behind." >&2
  exit 1
fi
echo "Downgrade to base removed all application tables"
if [[ "$(psql_test "SELECT count(*) FROM pg_proc
    WHERE proname = 'heroos_current_company_id';")" != "0" ]]; then
  echo "Downgrade to base left heroos_current_company_id() behind." >&2
  exit 1
fi
echo "Downgrade to base removed the tenant context function"

log "Upgrading base -> head again"
alembic upgrade head
assert_at_head
assert_schema
alembic check
