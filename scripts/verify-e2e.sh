#!/usr/bin/env bash
# Local end-to-end validation of founder onboarding, tenant isolation and the
# browser/BFF/API security boundaries, with the real components together:
#
#   Chrome --> Next.js standalone server (TLS) --> FastAPI (Uvicorn, TLS,
#   HEROOS_ENV=staging) --> PostgreSQL 16 (all Alembic migrations, RLS,
#   runtime and operator logins), signed in through a local OpenID Provider.
#
# Everything is disposable and created for this run only:
# - a PostgreSQL container with no volume (data on tmpfs), its own name, label
#   and ports. Docker Compose is not used, so the `heroos-local` project and its
#   volume are never touched (checked before and after);
# - generated passwords, TLS keys and signing keys in a private temporary
#   directory, deleted at the end. Nothing is read from the root .env.
#
# Results (no secrets, synthetic data only): e2e/.output/<UTC timestamp>/.
# Options (environment): E2E_SKIP_BUILD=1 reuses an existing web build;
# E2E_SUITES=a,b runs only those suites; E2E_KEEP_RUN_DIR=1 keeps the temporary
# directory (it contains this run's throwaway secrets).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

random_hex() {
  od -An -tx1 -N"$1" /dev/urandom | tr -d ' \n'
}

log() {
  printf '\n==> %s\n' "$*"
}

IMAGE="${E2E_POSTGRES_IMAGE:-postgres:16-alpine}"
DB_PORT="${E2E_DB_PORT:-55440}"
ISSUER_PORT="${E2E_ISSUER_PORT:-55441}"
API_PORT="${E2E_API_PORT:-55442}"
WEB_INTERNAL_PORT="${E2E_WEB_INTERNAL_PORT:-55443}"
WEB_PORT="${E2E_WEB_PORT:-55444}"
CHROME_PORT="${E2E_CHROME_PORT:-55445}"
ISSUER2_PORT="${E2E_ISSUER2_PORT:-55446}"
API2_PORT="${E2E_API2_PORT:-55447}"
PROTECTED_VOLUME="heroos-local_heroos_postgres_data"

RUN_ID="$(random_hex 4)"
CONTAINER="heroos-e2e-pg-${RUN_ID}"
DATABASE="heroos_e2e"
OWNER="heroos_e2e_owner"
OWNER_PASSWORD="$(random_hex 32)"
RUNTIME_LOGIN="heroos_app_e2e_${RUN_ID}"
RUNTIME_PASSWORD="$(random_hex 32)"
OPERATOR_LOGIN="heroos_op_e2e_${RUN_ID}"
OPERATOR_PASSWORD="$(random_hex 32)"
SESSION_SECRET="$(random_hex 32)"
OUTPUT_DIR="${E2E_OUTPUT_DIR:-${REPO_ROOT}/e2e/.output/$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/heroos-e2e.XXXXXX")"
chmod 700 "${RUN_DIR}"
mkdir -p "${OUTPUT_DIR}"

volume_fingerprint() {
  if docker volume inspect "${PROTECTED_VOLUME}" >/dev/null 2>&1; then
    docker volume inspect "${PROTECTED_VOLUME}" --format '{{.CreatedAt}} {{.Mountpoint}} {{json .Labels}}'
    printf 'attached:%s\n' "$(docker ps -aq --filter "volume=${PROTECTED_VOLUME}" | tr '\n' ' ')"
  else
    echo "absent"
  fi
}

cleanup() {
  local status=$?
  if docker inspect "${CONTAINER}" --format '{{index .Config.Labels "heroos.e2e.run"}}' 2>/dev/null | grep -qx "${RUN_ID}"; then
    docker rm -f "${CONTAINER}" >/dev/null || { echo "WARNING: could not remove ${CONTAINER}" >&2; status=1; }
  fi
  if [[ "${E2E_KEEP_RUN_DIR:-0}" == "1" ]]; then
    echo "Kept ${RUN_DIR} (contains this run's throwaway secrets; delete it when done)." >&2
  else
    rm -rf "${RUN_DIR}"
  fi
  local after
  after="$(volume_fingerprint)"
  if [[ "${after}" != "${PROTECTED_VOLUME_BEFORE}" ]]; then
    echo "ERROR: ${PROTECTED_VOLUME} changed during the run" >&2
    status=1
  else
    echo "Protected volume ${PROTECTED_VOLUME}: unchanged, no container attached by this run."
  fi
  if [[ ${status} -eq 0 ]]; then
    log "End-to-end verification PASSED (results: ${OUTPUT_DIR})"
  else
    log "End-to-end verification FAILED (exit ${status}; results: ${OUTPUT_DIR})" >&2
  fi
  exit "${status}"
}

PROTECTED_VOLUME_BEFORE="$(volume_fingerprint)"
trap cleanup EXIT

log "Pre-flight"
for port in "${DB_PORT}" "${ISSUER_PORT}" "${API_PORT}" "${WEB_INTERNAL_PORT}" "${WEB_PORT}" "${CHROME_PORT}" "${ISSUER2_PORT}" "${API2_PORT}"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    echo "Refusing to run: port ${port} is already in use (set E2E_*_PORT)." >&2
    exit 1
  fi
done
command -v "${E2E_CHROME:-google-chrome}" >/dev/null || { echo "Chrome not found (E2E_CHROME)." >&2; exit 1; }

log "Starting disposable PostgreSQL (${IMAGE}, container ${CONTAINER}, tmpfs, no volume)"
# Published on 127.0.0.1 (migrations, role bootstrap, operator CLI) and on
# 127.0.0.2 (the API): with HEROOS_ENV=staging the API refuses the local
# development host names, exactly as in deployment.
docker run -d --name "${CONTAINER}" \
  --label heroos.e2e=1 --label "heroos.e2e.run=${RUN_ID}" \
  -e POSTGRES_USER="${OWNER}" -e POSTGRES_PASSWORD="${OWNER_PASSWORD}" -e POSTGRES_DB="${DATABASE}" \
  --tmpfs /var/lib/postgresql/data:rw \
  -p "127.0.0.1:${DB_PORT}:5432" -p "127.0.0.2:${DB_PORT}:5432" \
  "${IMAGE}" >/dev/null
for _ in $(seq 1 60); do
  # TCP inside the container answers only after initialisation has finished.
  if docker exec -e PGPASSWORD="${OWNER_PASSWORD}" "${CONTAINER}" \
      psql -h 127.0.0.1 -U "${OWNER}" -d "${DATABASE}" -qtAc 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec -e PGPASSWORD="${OWNER_PASSWORD}" "${CONTAINER}" \
  psql -h 127.0.0.1 -U "${OWNER}" -d "${DATABASE}" -qtAc 'SELECT version()'

ADMIN_URL="postgresql+psycopg://${OWNER}:${OWNER_PASSWORD}@127.0.0.1:${DB_PORT}/${DATABASE}"
RUNTIME_URL_LOCAL="postgresql+psycopg://${RUNTIME_LOGIN}:${RUNTIME_PASSWORD}@127.0.0.1:${DB_PORT}/${DATABASE}"
OPERATOR_URL="postgresql+psycopg://${OPERATOR_LOGIN}:${OPERATOR_PASSWORD}@127.0.0.1:${DB_PORT}/${DATABASE}"
CLEAN_ENV=(env -i "PATH=${PATH}" "HOME=${HOME}")
[[ -n "${UV_CACHE_DIR:-}" ]] && CLEAN_ENV+=("UV_CACHE_DIR=${UV_CACHE_DIR}")

log "Applying all migrations as the schema owner"
(cd apps/api && "${CLEAN_ENV[@]}" MIGRATION_DATABASE_URL="${ADMIN_URL}" uv run --frozen alembic upgrade head)

log "Bootstrapping the disposable runtime and operator logins"
(cd apps/api && "${CLEAN_ENV[@]}" MIGRATION_DATABASE_URL="${ADMIN_URL}" DATABASE_URL="${RUNTIME_URL_LOCAL}" \
  uv run --frozen python -m scripts.bootstrap_runtime_role)
(cd apps/api && "${CLEAN_ENV[@]}" MIGRATION_DATABASE_URL="${ADMIN_URL}" HEROOS_OPERATOR_DATABASE_URL="${OPERATOR_URL}" \
  uv run --frozen python -m scripts.bootstrap_runtime_role --operator)

if [[ "${E2E_SKIP_BUILD:-0}" != "1" || ! -f apps/web/.next/standalone/apps/web/server.js ]]; then
  log "Building the web app (production)"
  pnpm --filter @heroos/web build
fi
# The standalone server serves static assets from next to itself, as in the image.
STANDALONE="apps/web/.next/standalone/apps/web"
rm -rf "${STANDALONE}/.next/static" "${STANDALONE}/public"
cp -r apps/web/.next/static "${STANDALONE}/.next/static"
cp -r apps/web/public "${STANDALONE}/public"

log "Generating throwaway TLS material"
mkdir -p "${RUN_DIR}/tls"
node e2e/lib/tls.mjs "${RUN_DIR}/tls"

log "Running the end-to-end suites"
"${CLEAN_ENV[@]}" \
  ${CI:+CI=1} \
  NODE_EXTRA_CA_CERTS="${RUN_DIR}/tls/ca.pem" \
  E2E_REPO_ROOT="${REPO_ROOT}" E2E_RUN_DIR="${RUN_DIR}" E2E_OUTPUT_DIR="${OUTPUT_DIR}" \
  E2E_CONTAINER="${CONTAINER}" E2E_RUN_ID="${RUN_ID}" E2E_DATABASE="${DATABASE}" E2E_OWNER="${OWNER}" \
  E2E_OWNER_PASSWORD="${OWNER_PASSWORD}" E2E_DB_PORT="${DB_PORT}" \
  E2E_RUNTIME_LOGIN="${RUNTIME_LOGIN}" E2E_RUNTIME_PASSWORD="${RUNTIME_PASSWORD}" \
  E2E_OPERATOR_LOGIN="${OPERATOR_LOGIN}" E2E_OPERATOR_PASSWORD="${OPERATOR_PASSWORD}" \
  E2E_SESSION_SECRET="${SESSION_SECRET}" \
  E2E_ISSUER_PORT="${ISSUER_PORT}" E2E_ISSUER2_PORT="${ISSUER2_PORT}" E2E_API2_PORT="${API2_PORT}" E2E_API_PORT="${API_PORT}" \
  E2E_WEB_INTERNAL_PORT="${WEB_INTERNAL_PORT}" E2E_WEB_PORT="${WEB_PORT}" E2E_CHROME_PORT="${CHROME_PORT}" \
  ${E2E_CHROME:+E2E_CHROME="${E2E_CHROME}"} ${E2E_SUITES:+E2E_SUITES="${E2E_SUITES}"} \
  node e2e/run.mjs
