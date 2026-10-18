# Local End-to-End Validation (`make e2e-check`)

**Status:** Introduced in M1-10E\
**Owner:** Technical Lead\
**Related:** [Customer Onboarding and Workspace UI](../architecture/web-onboarding.md),
[Authentication](../architecture/authentication.md),
[Tenant Isolation](../architecture/tenant-isolation.md),
[Staging activation runbook](staging-activation.md),
[M1-10E validation report](reports/2026-10-14-m1-10e-security-e2e-validation.md)

The unit, component and tenant-isolation suites test each layer on its own.
`make e2e-check` runs **the real components together** and attacks the seams
between them:

```text
Chrome (DevTools protocol, headless)
  └─ https ─▶ TLS terminator ─▶ Next.js standalone server (production build)
                                   └─ https ─▶ FastAPI under Uvicorn, HEROOS_ENV=staging
                                                 └─▶ PostgreSQL 16: every Alembic migration,
                                                     RLS, runtime login, operator login
  local OpenID Provider (https): discovery, JWKS, hosted login page,
  Authorization Code + PKCE, RFC 9068 access tokens, RP-initiated logout
```

## 1. What is real and what is simulated

| Component | In the run |
| --- | --- |
| Web app | The production build (`next build`), run as the standalone server the container image runs, with production settings (`NODE_ENV=production`, https origin, sealed cookies) |
| API | The FastAPI application under Uvicorn with `HEROOS_ENV=staging` and `HEROOS_AUTH_PROVIDER=oidc`. Its production OIDC verifier fetches discovery and keys over verified TLS |
| Database | PostgreSQL 16 with all migrations, connected as an RLS-restricted runtime login created by `scripts.bootstrap_runtime_role` |
| Lifecycle changes | The real operator CLI (`scripts.manage_identities`) with a disposable operator login: provision, grant, revoke, suspend, set-role, bind-identity, confirm-jurisdiction |
| Identity provider | **Simulated**: a strict local OpenID Provider (`e2e/lib/oidc-issuer.mjs`). Exact client and redirect-URI registration, S256 only, single-use codes, the API audience, RS256 RFC 9068 tokens. It replaces Auth0, not any HeroOS code |
| TLS | A throwaway CA per run. Each process trusts exactly that CA (`SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, Chrome's SPKI pin). Verification is never switched off |
| Hosting platform | **Simulated where it matters**: the browser suite can make the TLS terminator send the `Cache-Control` the live Vercel deployment was observed to send |

Nothing in the application has a test mode or a test login. The provider is
configured exactly as Auth0 is: an issuer URL, a client ID and an audience.

## 2. Safety

- **Disposable database only.** One `postgres:16-alpine` container per run, with
  its data on `tmpfs` (no volume). It has a random name and the label
  `heroos.e2e.run=<id>`, and is removed at the end. Docker Compose is not used,
  so the `heroos-local` project and its volume are never touched. The script
  records the volume's fingerprint before and after the run and fails if it
  changed.
- **No shared credentials.** The root `.env` is never read. Every password,
  session secret, TLS key and signing key is generated for the run in a private
  temporary directory (mode 0700), passed through the environment (never on a
  command line) and deleted at the end. `E2E_KEEP_RUN_DIR=1` keeps it, for
  debugging only.
- **No external service** is contacted: no Auth0, Render, Vercel or Supabase.
- **Synthetic data only.** Subjects look like `e2e|<run id>-<name>` and
  Company names start with `[SYNTHETIC E2E]`.
- **Ports.** It needs these ports free on 127.0.0.1, overridable with
  `E2E_*_PORT`, and refuses to start if one is taken:
  - 55440: database;
  - 55441 and 55446: the two test providers;
  - 55442 and 55447: the APIs;
  - 55443 and 55444: the web server;
  - 55445: Chrome.

  The database is also published on 127.0.0.2, because `HEROOS_ENV=staging`
  refuses local development host names, as it does in deployment.

## 3. Running it

Prerequisites:
- Docker;
- `uv`, `pnpm` and Node.js 22 (the repository's toolchain);
- Google Chrome (`E2E_CHROME` to point elsewhere);
- the `postgres:16-alpine` image;
- full Git history (the migration suite exports `371dd50` and `169261d`).

```bash
make e2e-check                       # build the web app, run every suite
E2E_SKIP_BUILD=1 make e2e-check      # reuse an existing web build
E2E_SUITES=registration,isolation make e2e-check
```

A full run takes roughly 10–15 minutes. Results go to
`e2e/.output/<UTC timestamp>/`, which is git-ignored:
- `results.md` and `results.json`: every check, with its evidence;
- `screenshots/`.

They contain synthetic data only, and no tokens or secrets. The run fails if
any check fails. Checks that cannot run in the environment are listed as
"not run" with the reason, never as passed.

## 4. Suites

| Suite | Covers |
| --- | --- |
| `api-auth` | Access-token validation through the real API: forged signature, `alg: none`, HS256 key confusion, issuer, audience, expiry, `nbf`, token type, ID-token claims, client allow-list, missing claims, unknown key; generic 401s; no CORS; no published schema |
| `registration` | Scenarios R1–R8: database-verified creation, double and concurrent submission, retry after a lost response, a second provider's binding, privileged or invalid payloads, the disabled flag (API restarted), revoked identity, suspended User, revoked or demoted founder |
| `isolation` | Two founders across Companies, Blueprints and cases; identical 403/404 answers; RLS as the real runtime login (with and without a candidate tenant context, transaction-local, write refusals); member vs administrator; operator promotion, demotion and revocation taking effect without sign-out |
| `jurisdiction` | Readiness for every licensing answer; refused confirmations; operator confirmation; withdrawal when the answer changes; unsupported ADGM; guidance only for `supported_confirmed` |
| `bff` | The sign-in flow over HTTP (state, PKCE, code replay, expired transaction, cancelled login, injected redirect parameters); cookie attributes; logout; session expiry; security headers; every BFF guard; backend 401, 403 and 404; API down; API frozen (timeout) |
| `browser` | The founder journey through hosted sign-up; validation; triple click; lost response and retry; disabled registration; suspended founder; cross-tenant URLs; switching; member write attempt; stale form after demotion; revocation; logout and Back (also with the live platform's caching headers); session expiry; jurisdiction display; responsive layout at 320–1440 px; keyboard; reduced motion; 200 % zoom; CSP and hydration console evidence |
| `cases` | M2-01 Disciplinary case journey in the browser: workspace → Disciplinary → empty list → New case (double click makes one case) → guided workspace → answers saved to PostgreSQL → reload → sign out and in → still there; an unconfirmed Company jurisdiction pauses the intake (jurisdiction-dependent steps unavailable); 390 px layout; three concurrent BFF creations with one key make one case; stale save 409 and replay applied once; a member gets no access at all (403 on every workflow route, the case records hide the case, administrator-only state in the browser); another Company gets 403/404; RLS hides facts and they cannot be rewritten; no title or narrative in any log |
| `intake` | M2-02 Disciplinary intake (UAE Federal Company confirmed by the operator) in the browser: initial facts → Case jurisdiction confirmed against the Company's confirmation (only its options offered) → incident context (follow-up appears only when asked; off-duty caution) → safety screening all No → intake recorded → one Yes → held for specialist review (factor named, no promise, no ticket table) → one evaluation per save in PostgreSQL → reload, sign out and in → hold and history kept → 390 px → a corrected answer is saved but never releases the hold; "Not sure" never clears the screening; an API with the default setting refuses the sensitive screening (409); a replay adds no evaluation; member 403, other Company 404; a DIFC Case gets no UAE Federal caution or screening and is held (API 409 on the screening, browser hold); RLS hides evaluations and they can be neither rewritten nor deleted; no content in any log |
| `progression` | M2-03 workflow progression with the fictional synthetic rule bundle the harness installs like a deployment (path + pinned SHA-256): a recorded intake offers the employer's own pathway choice (synthetic rules announced, nothing suggested) → pathway recorded → only the first stage can start → completion refused until the checklist is answered (missing and "No" explained, no button) → completed, next stage available, events in PostgreSQL with the bundle version → reload, sign out and in → everything kept → 390 px; via the API: skipping refused and recorded, a replay applied once, a stale revision 409, member 403, other Company 404, an escalation recorded on save that neither a changed answer nor an acknowledgment releases, an intake hold escalating every transition, an API without rules saying so and refusing (409, nothing recorded); RLS hides progress events and they can be neither rewritten nor deleted; no content in any log; no rule content in the browser assets |
| `decisions` | M2-04 employer decision records and the unified case history, on a Case with a stage in progress (synthetic rules): the section says what a record is and isn't and lists the limits → an empty form is stopped in the browser → a record with a named decision-maker, a date, an explanation and an evidence reference is saved once as the signed-in administrator and appears at once in the history, the workflow unchanged → a correction becomes the current version, the original kept and marked replaced → reload, sign out and in → everything kept → 390 px; via the API: a retry saved once, a stale revision 409, racing corrections serialized (one 200), member 403, other Company 404, a cross-case correction 404, forged actor/approval, unsafe category and links refused (422, not echoed), a record that can't complete a stage or release a hold, records saved without installed rules, history paging (and the BFF read: same-origin only) covering every entry once, no sensitive answer in any history; RLS hides records, they can be neither rewritten nor deleted and the database refuses unsafe categories; no record text in any log; no document or penalty table |
| `migration` | The staging transition rehearsed in order, with real API processes: `371dd50` on the demo schema, backup, B1a (and its guards), `169261d`, B1b, C1, the M1-10C API (`2f0fad8`) on C1, D1 (M2-01 workflow tables), the M2-01 API (`e4378f7`) on D1 and on D2 (M2-02 intake evaluations), the M2-02 API (`80adbae`) on D2 and on D3 (M2-03 progress events), the M2-03 API (`2e6d21f`) on D3 and on D4 (M2-04 decision records; the current API refuses C1 to D3 and starts on D4), appointing administrators, the downgrade guards (C1 history; D1 workflow data; D2, D3 and D4 reversible while empty, refused with an evaluation, a progress event or a decision record), restore of the D4 backup (revocation reconciliation) and restore of the pre-B1a backup |

## 5. The other database gates, without touching `heroos-local`

`make migration-check`, `make tenant-isolation-check` and
`make backup-restore-check` run `docker compose exec db`. `compose.yaml` pins
the project name `heroos-local`, so a plain run creates and drops its disposable
test databases and roles **inside the local development cluster**. When that
cluster or its volume must stay untouched, run them on a throwaway project
instead, as M1-10E did:

```bash
# override.yaml: own image, no restart, own port, no volume
services:
  db:
    image: postgres:16-alpine
    restart: "no"
    ports: !override ["127.0.0.1:55470:5432"]
    volumes: !reset []
    tmpfs: [/var/lib/postgresql/data]
```

```bash
export COMPOSE_PROJECT_NAME=heroos-gates-tmp
export COMPOSE_FILE="$PWD/compose.yaml:/abs/path/override.yaml"   # absolute paths
export COMPOSE_ENV_FILES=/abs/path/empty.env                      # never the root .env
export HEROOS_DB_ADMIN_PASSWORD="$(openssl rand -hex 32)" HEROOS_DB_APP_PASSWORD="$(openssl rand -hex 32)"
export MIGRATION_TEST_DB_PORT=55470 TENANT_TEST_DB_PORT=55470 BACKUP_TEST_DB_PORT=55470
docker compose config | grep -E '^name:|image: postgres|published|source:'   # check first
docker compose up -d --wait db
make migration-check tenant-isolation-check backup-restore-check
docker compose down --volumes
```

## 6. Extending it

- A suite is `e2e/suites/<name>.mjs` exporting `run(ctx)`; add its name to
  `SUITES` in `e2e/run.mjs`. Record every assertion with
  `ctx.check(id, name, ok, evidence)`. Use `ctx.report.notRun(...)` for anything
  that cannot run here.
- Use `ctx.token(subject)` for API calls and `ctx.signIn(page, subject)` for the
  real browser sign-in. `ctx.session(token)` builds a session cookie directly,
  for speed.
- Change identities and roles with `ctx.fixtures.operator([...], subject)`.
  Write rows directly (`ownerQuery`) only for data with no write path yet (for
  example cases).
- Keep it dependency-free: Node's standard library, the system Chrome and the
  repository's own toolchain.
