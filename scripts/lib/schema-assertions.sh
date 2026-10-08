#!/usr/bin/env bash
# Shared catalog assertions for the HeroOS schema and its M1-06 security
# controls: expected tables and constraints, Row-Level Security tables, one
# tenant_isolation policy per tenant table, and the NOLOGIN runtime privilege
# role. Sourced by verify-migrations.sh (migrated database) and
# verify-backup-restore.sh (restored database), so both prove the same thing.
#
# Requires DB_USER and the local Docker Compose `db` service; run from the repo root.

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

psql_db() {
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "$1" -qtAc "$2"
}

# assert_schema <database>
assert_schema() {
  local db="$1" actual expected missing=()

  actual="$(psql_db "${db}" "SELECT string_agg(table_name, ' ' ORDER BY table_name)
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
    if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_constraint c
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
  if [[ "$(psql_db "${db}" "SELECT pg_get_constraintdef(oid) FROM pg_constraint
      WHERE conname = 'fk_cases_company_id_subject_id_case_subjects';")" \
      != "FOREIGN KEY (company_id, subject_id) REFERENCES case_subjects(company_id, id) ON DELETE SET NULL (subject_id)" ]]; then
    echo "Composite case subject foreign key has an unexpected definition." >&2
    return 1
  fi
  echo "Composite tenant-safe case -> case_subject FK OK"

  actual="$(psql_db "${db}" "SELECT string_agg(relname, ' ' ORDER BY relname) FROM pg_class
    WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relrowsecurity;")"
  expected="${RLS_TABLES[*]}"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Unexpected Row-Level Security tables." >&2
    echo "  expected: ${expected}" >&2
    echo "  actual:   ${actual}" >&2
    return 1
  fi
  # Exactly one permissive FOR ALL policy per table, with USING and WITH CHECK.
  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_policies WHERE schemaname = 'public'
      AND policyname = 'tenant_isolation' AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
      AND qual LIKE '%heroos_current_company_id()%'
      AND with_check LIKE '%heroos_current_company_id()%';")" != "${#RLS_TABLES[@]}" \
      || "$(psql_db "${db}" "SELECT count(*) FROM pg_policies WHERE schemaname = 'public';")" \
      != "${#RLS_TABLES[@]}" ]]; then
    echo "Unexpected tenant isolation policies." >&2
    psql_db "${db}" "SELECT tablename, policyname, permissive, cmd, qual, with_check
      FROM pg_policies WHERE schemaname = 'public';" >&2
    return 1
  fi
  echo "RLS OK: ${actual} (one tenant_isolation policy each)"

  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}'
      AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcanlogin;")" != "1" ]]; then
    echo "Runtime role ${RUNTIME_ROLE} is missing or privileged." >&2
    return 1
  fi
  echo "Runtime privilege role ${RUNTIME_ROLE} OK (NOLOGIN, no SUPERUSER, no BYPASSRLS)"
}
