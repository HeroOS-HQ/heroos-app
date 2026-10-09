# HeroOS Preview Operations: Startup, Health and Recovery

**Status:** Current for the temporary VPS preview\
**Owner:** Technical Lead\
**Scope:** The temporary, synthetic-data VPS preview (Docker Compose behind Caddy). The official staging and production environments remain the M5 AWS architecture ([Production Security Gates](../architecture/production-security-gates.md))\
**Related:** [Database Credentials](database-credentials.md), [Backup and Recovery](../architecture/backup-and-recovery.md)

The preview holds synthetic data only. Never load real employee data into it.

## 1. Topology

```text
Internet ──443/TLS──▶ Caddy (host service, Basic Auth) ──▶ 127.0.0.1:3002  web (Next.js)
                                                            127.0.0.1:8001  api (FastAPI)       not proxied
                                                            127.0.0.1:5433  db  (PostgreSQL 16) not proxied
```

- Caddy (`/etc/caddy/Caddyfile`, host-managed, not in this repository) terminates
  TLS, requires HTTP Basic Auth for every request and proxies only to the web
  container. The API and the database are not reachable through it.
- `compose.yaml` publishes all three containers on **127.0.0.1 only**
  (`test_credential_hygiene.py` enforces this).
- Database credentials live only in the untracked root `.env`
  ([Database Credentials](database-credentials.md)). The API container receives
  only `HEROOS_ENV` and the runtime-role `DATABASE_URL`.
- PostgreSQL data lives in the named volume `heroos-local_heroos_postgres_data`.
  Containers can be recreated freely; the volume must never be removed.

## 2. Restart behaviour

All three services use `restart: unless-stopped` (`test_compose_reliability.py`):

| Event | Result |
|---|---|
| Container process crashes | Docker restarts it |
| VPS reboot or Docker daemon restart | Docker starts all three again, provided `docker` and `containerd` are enabled at boot (they are; check with `systemctl is-enabled docker containerd`) |
| `docker compose stop` (planned maintenance) | Containers stay stopped, also across reboots, until `docker compose up -d` |

After a reboot the Docker daemon starts the containers without Compose's
`depends_on` ordering. If the API starts before PostgreSQL is ready, its startup
check fails, the container exits and Docker restarts it until the database is
healthy. This normally settles within seconds and needs no action.

Caddy is a host service, enabled at boot (`systemctl is-enabled caddy`).

## 3. Health checks

| Component | Check | Healthy |
|---|---|---|
| db | Compose `pg_isready` every 5 s | `docker compose ps` shows `healthy` |
| api | Image `HEALTHCHECK` on `/health` every 30 s | `healthy`; `curl -fsS http://127.0.0.1:8001/health` returns `{"status":"ok"}` |
| web | Compose `fetch()` of `/` every 10 s | `healthy`; `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3002/` returns `200` |
| HTTPS preview | Caddy | `curl -s -o /dev/null -w '%{http_code} %{ssl_verify_result}' https://heroos-preview.duckdns.org/` returns `401 0` (Basic Auth required, valid certificate) |

```bash
cd ~/Pictures/heroos-app
docker compose ps --format '{{.Name}} {{.Status}}'
docker inspect -f '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} restarts={{.RestartCount}}' \
  heroos-local-db-1 heroos-local-api-1 heroos-local-web-1
```

## 4. Start, recover and update

**Start or recover** (after a reboot that did not bring everything back, or
after a planned `docker compose stop`):

```bash
cd ~/Pictures/heroos-app
make env-check                       # .env present, private, generated credentials
docker compose up -d --wait          # creates/starts missing containers; the volume is reused
docker compose ps --format '{{.Name}} {{.Status}}'
curl -fsS http://127.0.0.1:8001/health
```

If a service stays unhealthy: `docker compose logs --no-color --tail 100 <service>`
(logs contain no credentials). Do not run `make db-setup`, migrations or a
restore to "fix" a container that will not start; find the cause first.

**Update the code** (an approved `main` commit):

```bash
cd ~/Pictures/heroos-app
test -z "$(git status --porcelain)" && git pull --ff-only origin main
make env-check && docker compose config --quiet
docker compose build api web         # running containers keep serving
docker compose up -d --wait          # recreates only services whose image or definition changed
```

`docker compose up -d` recreates every service whose definition changed. A
`db` recreation is a short database restart with the same volume.

**Never:** `docker compose down -v`, `docker volume rm`/`prune` on this host,
`docker compose config` without `--quiet` (it prints credentials), or editing
`.env` by hand (use `make env-rotate`).

## 5. Rotate credentials

Use [Database Credentials §4](database-credentials.md): back up and verify the
backup (Gates 0–2), `make env-rotate BACKUP_DIR=<private dir>`, then
`make db-apply-credentials CONFIRM=yes && docker compose up -d --no-deps --force-recreate --wait api`,
then verify (Gate 7). `.env` changes alone never affect running containers.

## 6. Exposure check

```bash
ss -ltnH | awk '{print $4}' | grep -E ':(3002|8001|5433)$'          # each must be 127.0.0.1:<port>
docker ps --format '{{.Names}} {{.Ports}}' | grep heroos-local        # 127.0.0.1:… only
curl -s -o /dev/null -w '%{http_code}\n' https://heroos-preview.duckdns.org/   # 401 without credentials
```

Host-level settings (firewall, SSH, other services listening on the host, DNS,
Caddy) are outside this repository and change only with explicit approval.
