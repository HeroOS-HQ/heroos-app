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
  company_events
  company_registrations
  identity_events
  membership_events
  memberships
  user_identities
  users
)

EXPECTED_CONSTRAINTS=(
  companies_pkey
  users_pkey
  ck_users_status
  ck_users_suspended_at
  user_identities_pkey
  fk_user_identities_user_id_users
  uq_user_identities_issuer_subject
  ck_user_identities_status
  ck_user_identities_revoked_at
  ck_user_identities_issuer_not_empty
  ck_user_identities_subject_not_empty
  memberships_pkey
  uq_memberships_company_id_id
  ck_memberships_status
  ck_memberships_revoked_at
  ck_memberships_role
  identity_events_pkey
  fk_identity_events_user_id_users
  fk_identity_events_identity_id_user_identities
  ck_identity_events_event_type
  ck_identity_events_actor_kind
  ck_identity_events_actor_reference
  membership_events_pkey
  fk_membership_events_company_id_companies
  fk_membership_events_company_id_membership_id_memberships
  fk_membership_events_user_id_users
  ck_membership_events_event_type
  ck_membership_events_actor_kind
  ck_membership_events_actor_reference
  ck_membership_events_role
  company_events_pkey
  fk_company_events_company_id_companies
  ck_company_events_event_type
  ck_company_events_actor_kind
  ck_company_events_actor_reference
  ck_company_events_jurisdiction
  company_registrations_pkey
  uq_company_registrations_user_id
  uq_company_registrations_company_id
  fk_company_registrations_identity_id_user_identities
  fk_company_registrations_user_id_users
  fk_company_registrations_company_id_companies
  fk_company_registrations_company_id_membership_id_memberships
  memberships_company_id_fkey
  memberships_user_id_fkey
  uq_memberships_company_user
  company_blueprints_pkey
  company_blueprints_company_id_fkey
  uq_company_blueprints_company_id
  ck_company_blueprints_employee_count_nonnegative
  ck_company_blueprints_licensing_location
  ck_company_blueprints_licensing_authority
  ck_company_blueprints_employment_jurisdiction
  ck_company_blueprints_jurisdiction_confirmation
  case_subjects_pkey
  case_subjects_company_id_fkey
  uq_case_subjects_company_id_id
  cases_pkey
  cases_company_id_fkey
  uq_cases_company_id_id
  fk_cases_company_id_subject_id_case_subjects
)

# Tenant-owned tables: one tenant_isolation policy each.
TENANT_RLS_TABLES=(
  case_subjects
  cases
  companies
  company_blueprints
  company_events
  company_registrations
  membership_events
  memberships
)
# Every table with Row-Level Security (sorted). `users` and `user_identities`
# are global identity tables with per-role lifecycle policies instead of a
# tenant policy; `identity_events` is owner-only (RLS, no policy) (ADR-008).
RLS_TABLES=(
  case_subjects
  cases
  companies
  company_blueprints
  company_events
  company_registrations
  identity_events
  membership_events
  memberships
  user_identities
  users
)
# Every other policy, as table:policy:permissive:command:roles.
LIFECYCLE_POLICIES=(
  "memberships:lifecycle_active:RESTRICTIVE:SELECT:{heroos_app_runtime}"
  "user_identities:identities_operator:PERMISSIVE:ALL:{heroos_identity_operator}"
  "user_identities:identities_runtime_read:PERMISSIVE:SELECT:{heroos_app_runtime}"
  "users:users_operator:PERMISSIVE:ALL:{heroos_identity_operator}"
  "users:users_runtime_read:PERMISSIVE:SELECT:{heroos_app_runtime}"
)
RUNTIME_ROLE=heroos_app_runtime
OPERATOR_ROLE=heroos_identity_operator

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
  # Exactly one permissive FOR ALL tenant policy per tenant table, with USING
  # and WITH CHECK, plus exactly the listed lifecycle policies and nothing else.
  actual="$(psql_db "${db}" "SELECT string_agg(tablename, ' ' ORDER BY tablename)
    FROM pg_policies WHERE schemaname = 'public'
      AND policyname = 'tenant_isolation' AND permissive = 'PERMISSIVE' AND cmd = 'ALL'
      AND roles = '{public}'
      AND qual LIKE '%heroos_current_company_id()%'
      AND with_check LIKE '%heroos_current_company_id()%';")"
  expected="${TENANT_RLS_TABLES[*]}"
  local lifecycle_actual lifecycle_expected
  lifecycle_actual="$(psql_db "${db}" "SELECT string_agg(
      tablename || ':' || policyname || ':' || permissive || ':' || cmd || ':' || roles::text,
      ' ' ORDER BY tablename, policyname)
    FROM pg_policies WHERE schemaname = 'public' AND policyname <> 'tenant_isolation';")"
  lifecycle_expected="${LIFECYCLE_POLICIES[*]}"
  if [[ "${actual}" != "${expected}" || "${lifecycle_actual}" != "${lifecycle_expected}" ]]; then
    echo "Unexpected Row-Level Security policies." >&2
    psql_db "${db}" "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check
      FROM pg_policies WHERE schemaname = 'public';" >&2
    return 1
  fi
  echo "RLS OK: tenant_isolation on ${actual}; lifecycle policies: ${lifecycle_actual}"

  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_roles WHERE rolname = '${RUNTIME_ROLE}'
      AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcanlogin;")" != "1" ]]; then
    echo "Runtime role ${RUNTIME_ROLE} is missing or privileged." >&2
    return 1
  fi
  echo "Runtime privilege role ${RUNTIME_ROLE} OK (NOLOGIN, no SUPERUSER, no BYPASSRLS)"

  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_roles WHERE rolname = '${OPERATOR_ROLE}'
      AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcanlogin
      AND NOT pg_has_role(rolname, '${RUNTIME_ROLE}', 'MEMBER');")" != "1" ]]; then
    echo "Identity operator role ${OPERATOR_ROLE} is missing, privileged or an API runtime role." >&2
    return 1
  fi
  # The audit writers are SECURITY DEFINER with a pinned, empty search_path and
  # no EXECUTE for PUBLIC.
  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_proc
      WHERE pronamespace = 'public'::regnamespace
        AND proname IN ('heroos_audit_identity_change', 'heroos_audit_membership_change',
                        'heroos_audit_company_change', 'heroos_register_company',
                        'heroos_identity_companies')
        AND prosecdef AND proconfig = ARRAY['search_path=\"\"']
        AND NOT has_function_privilege('public', oid, 'EXECUTE');")" != "5" ]]; then
    echo "Audit and registration functions are not pinned SECURITY DEFINER functions." >&2
    return 1
  fi
  echo "Identity operator role ${OPERATOR_ROLE} OK; audit trigger functions pinned"

  # No role other than the owner and the two HeroOS groups holds any table
  # privilege (portable: also catches Supabase default privileges for anon,
  # authenticated and service_role, which never exist locally).
  local outsiders
  outsiders="$(psql_db "${db}" "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
      AND a.grantee <> c.relowner
      AND a.grantee NOT IN (SELECT oid FROM pg_roles
                            WHERE rolname IN ('${RUNTIME_ROLE}', '${OPERATOR_ROLE}'));")"
  if [[ "${outsiders}" != "0" ]]; then
    echo "Unexpected table privileges for roles outside HeroOS (${outsiders})." >&2
    return 1
  fi
  # Audit tables refuse TRUNCATE (statement-level append-only trigger).
  if [[ "$(psql_db "${db}" "SELECT count(*) FROM pg_trigger
      WHERE tgname = 'heroos_append_only_truncate'
        AND tgrelid IN ('public.identity_events'::regclass, 'public.membership_events'::regclass,
                        'public.company_events'::regclass,
                        'public.company_registrations'::regclass);")" != "4" ]]; then
    echo "Audit tables are missing their TRUNCATE guard." >&2
    return 1
  fi
  echo "Table ACLs OK (owner and HeroOS groups only); audit TRUNCATE guards present"

  # M1-10C: the API role cannot create or delete Companies, change Memberships
  # or write the trusted jurisdiction confirmation (column-level grants).
  if [[ "$(psql_db "${db}" "SELECT count(*) FROM unnest(ARRAY['employment_jurisdiction',
        'confirmed_licensing_location', 'confirmed_licensing_authority',
        'jurisdiction_confirmed_at']) AS c(name)
      WHERE has_column_privilege('${RUNTIME_ROLE}', 'public.company_blueprints', c.name,
                                 'INSERT, UPDATE');")" != "0" \
     || "$(psql_db "${db}" "SELECT has_table_privilege('${RUNTIME_ROLE}', 'public.companies',
        'INSERT, DELETE, TRUNCATE') OR has_table_privilege('${RUNTIME_ROLE}',
        'public.memberships', 'INSERT, UPDATE, DELETE, TRUNCATE')
        OR has_column_privilege('${RUNTIME_ROLE}', 'public.memberships', 'role', 'UPDATE');")" != "f" ]]; then
    echo "Runtime role ${RUNTIME_ROLE} can create Companies, change Memberships or confirm jurisdictions." >&2
    return 1
  fi
  echo "Runtime role write boundary OK (no Company creation, Membership or confirmation writes)"
}
