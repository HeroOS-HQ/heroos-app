#!/usr/bin/env bash
# Database credentials for the verification scripts
# (docs/operations/database-credentials.md).
#
# - The admin password comes from HEROOS_DB_ADMIN_PASSWORD in the environment,
#   else from the root .env. There is no default: missing means stop.
# - Each run uses its own disposable runtime login role with a random password
#   (`new_disposable_runtime_role`), never the shared `heroos_app` role. Roles
#   are cluster-wide, so managing `heroos_app` from a test would change the
#   live API credential. The live role's password is fingerprinted before and
#   checked after every run (`assert_live_runtime_role_unchanged`).
# - Nothing here prints a password, a verifier or a URL.
#
# Requires REPO_ROOT, DB_USER and the Docker Compose `db` service.

LIVE_RUNTIME_ROLE=heroos_app
DISPOSABLE_ROLE_PATTERN='^heroos_app_t_[0-9a-f]{8}$'
DISPOSABLE_OPERATOR_PATTERN='^heroos_op_t_[0-9a-f]{8}$'

# env_file_value KEY: last KEY=value in the root .env (no shell evaluation).
env_file_value() {
  local key="$1" file="${REPO_ROOT}/.env" line
  [[ -f "${file}" ]] || return 0
  line="$(grep -E "^(export[[:space:]]+)?${key}=" "${file}" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "${line}"
}

# Sets DB_PASSWORD (admin role) or exits.
require_admin_password() {
  DB_PASSWORD="${HEROOS_DB_ADMIN_PASSWORD:-$(env_file_value HEROOS_DB_ADMIN_PASSWORD)}"
  if [[ -z "${DB_PASSWORD}" ]]; then
    echo "HEROOS_DB_ADMIN_PASSWORD is not set (environment or root .env); run \`make env-init\`." >&2
    exit 1
  fi
}

random_hex() {
  od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'
}

# Sets RUNTIME_LOGIN / RUNTIME_PASSWORD to a fresh disposable role identity.
new_disposable_runtime_role() {
  RUNTIME_LOGIN="heroos_app_t_$(random_hex 4)"
  RUNTIME_PASSWORD="$(random_hex 32)"
}

# Sets OPERATOR_LOGIN / OPERATOR_PASSWORD to a fresh disposable identity
# operator login (ADR-008); never a real operator's login.
new_disposable_operator_role() {
  OPERATOR_LOGIN="heroos_op_t_$(random_hex 4)"
  OPERATOR_PASSWORD="$(random_hex 32)"
}

_psql_postgres() {
  docker compose exec -T -e PGOPTIONS=--client-min-messages=warning db \
    psql -X -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres -qtAc "$1"
}

# drop_disposable_runtime_role <role>: only ever drops heroos_app_t_<8 hex>.
drop_disposable_runtime_role() {
  local role="$1"
  if [[ ! "${role}" =~ ${DISPOSABLE_ROLE_PATTERN} ]]; then
    echo "Refusing to drop role '${role}': not a disposable test role." >&2
    return 1
  fi
  _psql_postgres "DROP ROLE IF EXISTS ${role};" >/dev/null
}

# drop_disposable_operator_role <role>: only ever drops heroos_op_t_<8 hex>.
drop_disposable_operator_role() {
  local role="$1"
  if [[ ! "${role}" =~ ${DISPOSABLE_OPERATOR_PATTERN} ]]; then
    echo "Refusing to drop role '${role}': not a disposable operator test role." >&2
    return 1
  fi
  _psql_postgres "DROP ROLE IF EXISTS ${role};" >/dev/null
}

# Opaque fingerprint of the live runtime role's credential and attributes. Kept
# in a shell variable and compared only; never printed.
live_runtime_role_fingerprint() {
  _psql_postgres "SELECT coalesce((SELECT md5(concat_ws('|', a.rolpassword, a.rolvaliduntil,
      a.rolsuper, a.rolbypassrls, a.rolcreaterole, a.rolcreatedb, a.rolcanlogin))
    FROM pg_authid a WHERE a.rolname = '${LIVE_RUNTIME_ROLE}'), 'absent');"
}

record_live_runtime_role() {
  LIVE_RUNTIME_ROLE_FINGERPRINT="$(live_runtime_role_fingerprint)"
}

assert_live_runtime_role_unchanged() {
  if [[ -z "${LIVE_RUNTIME_ROLE_FINGERPRINT:-}" ]]; then
    return 0
  fi
  if [[ "$(live_runtime_role_fingerprint)" != "${LIVE_RUNTIME_ROLE_FINGERPRINT}" ]]; then
    echo "The live ${LIVE_RUNTIME_ROLE} role credential or attributes changed during this run." >&2
    return 1
  fi
  echo "Live ${LIVE_RUNTIME_ROLE} role untouched (credential and attributes unchanged)"
}
