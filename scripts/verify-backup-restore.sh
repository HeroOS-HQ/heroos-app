#!/usr/bin/env bash
# Verify the HeroOS logical backup/restore procedure end to end, on disposable
# databases only (docs/architecture/backup-and-recovery.md):
#
#   create disposable source DB -> migrate (admin role) -> bootstrap a disposable
#   runtime login role (heroos_app_t_<hex>, never the live heroos_app)
#   -> seed synthetic data -> pg_dump (custom format, 0600, private dir)
#   -> create empty disposable restore DB -> pg_restore (admin role)
#   -> shared schema/RLS/role assertions -> Alembic head + drift check
#   -> data, catalog, grants and runtime-role tenant isolation suite
#   -> refusal checks -> drop both DBs and delete the archive (always)
#
# Uses only the local Docker Compose `db` service (CI starts the same service)
# and its PostgreSQL 16 client tools. Never touches the normal development
# database or the live heroos_app role (checked before/after). Credentials from
# the environment or the root .env (`make env-init`); no AWS, no production data.
set -euo pipefail
# Everything this script creates (workdir, archive) is private.
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DB_USER="${POSTGRES_USER:-heroos}"
# shellcheck source=lib/credentials.sh
source "${REPO_ROOT}/scripts/lib/credentials.sh"
require_admin_password
DB_HOST="${BACKUP_TEST_DB_HOST:-localhost}"
DB_PORT="${BACKUP_TEST_DB_PORT:-5433}"
SOURCE_DB="${BACKUP_TEST_SOURCE_DB:-heroos_backup_source_test}"
RESTORE_DB="${BACKUP_TEST_RESTORE_DB:-heroos_backup_restore_test}"
PG_TOOLS="${BACKUP_TEST_PG_TOOLS:-compose}"
# Disposable runtime login role for this run only (never the shared heroos_app:
# roles are cluster-wide). Dropped on exit.
new_disposable_runtime_role

# Safety guards: only ever operate on clearly disposable databases.
if [[ ! "${SOURCE_DB}" =~ ^[a-z0-9_]+_backup_source_test$ ]]; then
  echo "Refusing to run: '${SOURCE_DB}' must match *_backup_source_test." >&2
  exit 1
fi
if [[ ! "${RESTORE_DB}" =~ ^[a-z0-9_]+_backup_restore_test$ ]]; then
  echo "Refusing to run: '${RESTORE_DB}' must match *_backup_restore_test." >&2
  exit 1
fi

# shellcheck source=lib/schema-assertions.sh
source "${REPO_ROOT}/scripts/lib/schema-assertions.sh"

admin_url() {
  printf 'postgresql+psycopg://%s:%s@%s:%s/%s' "${DB_USER}" "${DB_PASSWORD}" "${DB_HOST}" "${DB_PORT}" "$1"
}
runtime_url() {
  printf 'postgresql+psycopg://%s:%s@%s:%s/%s' "${RUNTIME_LOGIN}" "${RUNTIME_PASSWORD}" "${DB_HOST}" "${DB_PORT}" "$1"
}

log() {
  printf '\n==> %s\n' "$*"
}

psql_admin() {
  docker compose exec -T -e PGOPTIONS=--client-min-messages=warning db \
    psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d postgres -qtAc "$1"
}

# Run the recovery tool as an operator would. Credentials travel only in the
# environment (MIGRATION_DATABASE_URL), never on a command line.
db_recovery() {
  (cd apps/api && MIGRATION_DATABASE_URL="$(admin_url postgres)" DATABASE_URL="$(runtime_url postgres)" \
    uv run python -m scripts.db_recovery --pg-tools "${PG_TOOLS}" "$@")
}

alembic_on() {
  local db="$1"
  shift
  (cd apps/api && MIGRATION_DATABASE_URL="$(admin_url "${db}")" uv run alembic "$@")
}

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

drop_disposable_dbs() {
  psql_admin "DROP DATABASE IF EXISTS ${SOURCE_DB} WITH (FORCE);" >/dev/null
  psql_admin "DROP DATABASE IF EXISTS ${RESTORE_DB} WITH (FORCE);" >/dev/null
}

WORKDIR=""

cleanup() {
  local status=$?
  log "Cleaning up disposable databases, runtime role and backup artifacts"
  drop_disposable_dbs || { echo "WARNING: failed to drop disposable databases" >&2; status=1; }
  drop_disposable_runtime_role "${RUNTIME_LOGIN}" || { echo "WARNING: failed to drop ${RUNTIME_LOGIN}" >&2; status=1; }
  assert_live_runtime_role_unchanged || status=1
  if [[ -n "${WORKDIR}" ]]; then
    rm -rf -- "${WORKDIR}"
    if [[ -e "${WORKDIR}" ]]; then
      echo "Backup workdir was not removed." >&2
      status=1
    else
      echo "Backup workdir and archive removed"
    fi
  fi
  remaining="$(psql_admin "SELECT count(*) FROM pg_database
    WHERE datname IN ('${SOURCE_DB}', '${RESTORE_DB}');" || echo unknown)"
  if [[ "${remaining}" != "0" ]]; then
    echo "Disposable databases still exist after cleanup (${remaining})." >&2
    status=1
  else
    echo "Disposable databases dropped"
  fi
  if [[ ${status} -eq 0 ]]; then
    log "Backup/restore verification PASSED"
  else
    log "Backup/restore verification FAILED (exit ${status})" >&2
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

record_live_runtime_role
trap cleanup EXIT
drop_disposable_dbs

# Private temporary directory outside the repository, removed on every exit.
WORKDIR="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/heroos-backup-check.XXXXXXXX")"
chmod 700 "${WORKDIR}"
ARCHIVE="${WORKDIR}/heroos-logical-backup.dump"

log "Creating and migrating disposable source database ${SOURCE_DB}"
psql_admin "CREATE DATABASE ${SOURCE_DB};" >/dev/null
alembic_on "${SOURCE_DB}" upgrade head
# Cluster-wide roles are not part of a database dump: bootstrap them first.
(cd apps/api && MIGRATION_DATABASE_URL="$(admin_url "${SOURCE_DB}")" \
  DATABASE_URL="$(runtime_url "${SOURCE_DB}")" uv run python -m scripts.bootstrap_runtime_role)

log "Seeding synthetic recovery dataset"
(cd apps/api && RECOVERY_TEST_SOURCE_URL="$(admin_url "${SOURCE_DB}")" \
  uv run python -m tests.recovery.fixture_data)

log "Backing up ${SOURCE_DB} (migration/admin role, custom format)"
db_recovery backup --database "${SOURCE_DB}" --output "${ARCHIVE}"
if [[ "$(file_mode "${WORKDIR}")" != "700" || "$(file_mode "${ARCHIVE}")" != "600" ]]; then
  echo "Backup artifacts are not private: dir $(file_mode "${WORKDIR}"), archive $(file_mode "${ARCHIVE}")." >&2
  exit 1
fi
echo "Backup artifacts private: workdir 700, archive 600"

log "Restoring into empty disposable database ${RESTORE_DB}"
psql_admin "CREATE DATABASE ${RESTORE_DB};" >/dev/null
db_recovery restore --database "${RESTORE_DB}" --input "${ARCHIVE}"

log "Asserting restored schema and M1-06 security controls"
assert_schema "${RESTORE_DB}"
current="$(alembic_on "${RESTORE_DB}" current 2>/dev/null | awk '{print $1}')"
head="$(alembic_on "${RESTORE_DB}" heads 2>/dev/null | awk '{print $1}')"
if [[ -z "${current}" || "${current}" != "${head}" ]]; then
  echo "Restored alembic revision (${current:-none}) is not head (${head})." >&2
  exit 1
fi
echo "Restored alembic revision is head: ${current}"
alembic_on "${RESTORE_DB}" check

log "Verifying restored data, catalog, grants and tenant isolation"
(cd apps/api && RECOVERY_TEST_SOURCE_URL="$(admin_url "${SOURCE_DB}")" \
  RECOVERY_TEST_RESTORED_URL="$(admin_url "${RESTORE_DB}")" \
  RECOVERY_TEST_RUNTIME_ROLE="${RUNTIME_LOGIN}" RECOVERY_TEST_RUNTIME_PASSWORD="${RUNTIME_PASSWORD}" \
  RECOVERY_TEST_REQUIRED=1 uv run pytest tests/recovery -v -p no:cacheprovider)

log "Checking the restore tool refuses unsafe targets"
for target in "${RESTORE_DB}" heroos postgres template1 heroos_production; do
  if db_recovery restore --database "${target}" --input "${ARCHIVE}" 2>"${WORKDIR}/refusal.log"; then
    echo "Restore into ${target} was not refused." >&2
    exit 1
  fi
  echo "Refused ${target}: $(tail -n 1 "${WORKDIR}/refusal.log")"
done
