# Preview Credential Rotation and Reliability: Completion Report (2026-10-09)

**Environment:** temporary VPS preview (synthetic data only), `https://heroos-preview.duckdns.org`\
**Procedures:** [Database Credentials §4](../database-credentials.md#4-phase-b-rotating-the-vps-preview-credentials), [Preview Operations](../preview-operations.md)\
**Secrets:** this report contains no credentials, password hashes or database URLs.

Status key: **Verified** = done and checked on the live preview; **Pending** = not done yet; **Out of scope** = needs separate approval.

## 1. Deployed commit

| Item | Value |
|---|---|
| Application and Compose configuration | `97ae5ae` (PR #11, restart policies), on top of `7e2aa0d` (PR #10, credential hardening) |
| CI on the deployed commit | 6/6 jobs successful (API, Web, Containers, Tenant Isolation, Backup & Restore, Privacy Decisions) |
| Live checkout | clean, in sync with `origin/main` |
| Images | api `3fe8eb206c74` (built from `7e2aa0d`; PR #11 changed no image input), web `d51a2869c0e8`, db `postgres:16-alpine` `721873c34ceb` |

## 2. Gates

| Gate | Result | Evidence |
|---|---|---|
| 0 Pre-flight | Verified | clean checkout, PR and CI green, 64-line database baseline |
| 1 Backup | Verified | `heroos.dump` (custom format), `roles.sql` without passwords, `SHA256SUMS` |
| 2 Restore verification | Verified (second run) | throwaway Compose project on tmpfs: checksums, schema assertions, restored copy equal to baseline (order-insensitive), revision = code head, no model drift, 17/17 runtime-role and RLS probes. First run stopped on a helper bug (constraint ordering by OID), fixed before the re-run |
| 3 Merge PR #10 | Verified | squash `7e2aa0d`, tree identical to tested head, `main` CI green |
| 4 New credentials | Verified | both database passwords and `HEROOS_DEV_AUTH_SECRET` rotated in `.env` (checked by key name), no other key changed |
| 5 Deploy code | Verified | live checkout pulled, API image built ahead of time, rollback tag kept until Gate 10 |
| 6 Apply and recreate API | Verified | two `ALTER ROLE … PASSWORD` (SCRAM verifiers) in one transaction, attributes and memberships unchanged; API recreated |
| 7 Verify | Verified | see §5 |
| 8 Container reconciliation | Verified | restart policies applied, `db` definition reconciled (see §4) |
| 9 Verification suites on the preview cluster | Verified | migration check passed; tenant isolation 134 passed; backup/restore 24 passed (5 unsafe restore targets refused); live database unchanged after each suite; no leftover `*_test` databases, `heroos_app_t_*` roles or work directories |
| 10 Cleanup | Verified | see §6 |

## 3. Restart policies (PR #11)

- `restart: unless-stopped` for `api`, `web`, `db`. `always` would restart
  services an operator stopped on purpose; `on-failure` would not start them
  after a reboot.
- Regression tests: `apps/api/tests/test_compose_reliability.py` (policy, named
  volume, dependency order, health checks).
- PR CI 6/6 green; `main` CI 6/6 green after the squash merge `97ae5ae`.
- `docker`, `containerd` and `caddy` are enabled at boot, so the policy takes
  effect after a reboot. Verified by inspection only; the VPS was not rebooted.

## 4. Container recreation and measured downtime

Measured with a probe every ~0.25 s (API `/health`, web `/`, `pg_isready`):

| Change | db | api | web |
|---|---|---|---|
| Gate 6: password change + API recreate | not restarted | **3.7 s** | not restarted (0 failed samples) |
| Gate 8: reconcile all three (one `docker compose up -d --wait`) | **5.8 s** | **11.3 s** | **14.1 s** |

Gate 8 degraded window, any service: 17.2 s. Before it, the resolved Compose
configuration differed from the running containers only in restart policy (all
three) and the `db` `POSTGRES_PASSWORD` source; afterwards there are no
differences and a dry run plans no further actions. Same images, same named
volume `heroos-local_heroos_postgres_data` (same creation time); PostgreSQL
reported "Skipping initialization" (existing data directory reused).

## 5. Database integrity and tenant isolation

| Check | Result |
|---|---|
| Database vs pre-deployment baseline | identical after Gates 6, 8, each Gate 9 suite and at the end: 64 lines covering roles and attributes, memberships, owners, RLS flags, row counts, constraints, the 5 `tenant_isolation` policies, grants, schema/function ACLs, databases and volume |
| Alembic revision | `97d4200fe7a2` (no migrations run against `heroos`) |
| Roles | `heroos` (admin), `heroos_app` (login; no SUPERUSER, BYPASSRLS, CREATEROLE, CREATEDB; member of `heroos_app_runtime`), `heroos_app_runtime` (NOLOGIN) |
| API database identity | only `heroos_app`, from the API container; API environment has only `HEROOS_ENV` and `DATABASE_URL` |
| Runtime role on live (read-only) | startup guard passes; no companies visible without tenant context; `alembic_version` denied; `row_security=off` rejected |
| Tenant isolation | 134-test suite passed against the preview cluster (disposable database and role); restored-copy probes in Gate 2 passed |
| Credentials | current accepted; retired (pre-rotation and committed defaults) refused; passwords stored as SCRAM-SHA-256; dev auth secret differs from the retired default |
| Secret exposure | 0 current or retired values in container logs, backup folder files, tracked files, the entire git history, the system journal or `/tmp` (counts only). Values are present only where intended: `.env`, the API `DATABASE_URL`, the db `POSTGRES_PASSWORD` |

## 6. Backup retention and cleanup

Kept, private (folder 0700, files 0600), outside the repository on the preview host:
`heroos.dump`, `roles.sql` (no passwords), `SHA256SUMS` (valid), the pre-deployment
baseline and final snapshot, the restored-copy snapshot, Gate 2/5/6/8/9 logs and
the verification helpers. Retention follows the pending decision PRIV-018.

Removed:

- the pre-rotation `.env` backup (retired credentials), with `shred`, after a final
  check that the retired credentials are refused and absent from all active
  configuration;
- the `heroos-api:pre-rotation` rollback image (not used by any container);
- the merged security worktree and the two local feature branches (trees
  identical to their squash merges, nothing uncommitted);
- intermediate snapshots (each verified identical to the baseline first), probe
  PID/timestamp files and hash-derived fingerprint files (shredded).

Git history was not rewritten. No volume or application data was deleted.

## 7. Remaining risks

| Risk | Status |
|---|---|
| Retired credentials remain in Git history | accepted; they authenticate nothing, and the tooling refuses to apply them |
| Other host services listen publicly besides SSH and Caddy; firewall state not verified (no sudo) | out of scope (host level); review with the host owner |
| The backup lives on the same host as the database | accepted for a synthetic-data preview; off-host backups are an M5 concern |
| After a reboot Docker starts containers without Compose ordering; the API restarts until PostgreSQL is healthy | expected, self-healing; documented |
| The db container environment holds the admin password (`POSTGRES_PASSWORD`, standard for the image), visible to `docker inspect` | accepted; Docker access is root-equivalent on this host |
| Remote branches `feature/db-credential-hardening`, `feature/preview-restart-policy`; older local M1 branches and images | housekeeping, optional |
| Caddy Basic Auth credential not rotated in this work | out of scope |

## 8. Final preview health

API `/health` 200; web 200; HTTPS 401 with `WWW-Authenticate: Basic` and a
valid Let's Encrypt certificate (expires 2027-01-07), wrong credentials rejected;
PostgreSQL accepting connections; all three containers healthy, 0 restarts,
`restart: unless-stopped`; ports 3002, 8001 and 5433 bound to 127.0.0.1 only;
`make env-check` 9/9 OK.

## 9. M2 readiness

**Infrastructure: ready.** The preview is secured, recoverable and verified, and
the procedures are documented.

**Application: not yet a usable HR product.** Facts from the repository at the
deployed commit:

- API: the only route is `/health`; tenant, auth and storage dependencies exist
  but no business endpoints use them.
- Web: a single placeholder page; no screens call the API.
- The preview API has no authentication provider configured, and Caddy proxies
  only the web app, so browsers cannot reach the API directly.

M2 therefore starts by deciding how JJ signs in to the preview (without enabling
development authentication shortcuts on a public URL) and by building the first
browser-visible slice end to end on the existing tenant-isolation foundation.
The M2 handoff review (scope, business decisions, first task) is the next step
and has not started.
