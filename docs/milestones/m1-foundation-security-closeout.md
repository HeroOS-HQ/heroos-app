# M1 — Foundation & Security: Closeout and M2 Readiness

**Status:** M1 verified complete on `main`. AWS Staging and live cloud activation deferred to M5 (post-closeout roadmap amendment, 2026-10-09; originally recorded as M3)\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security\
**Issue:** M1-09 — Verify M1 foundation & M2 readiness\
**Verified base:** `main` at `43eb33e6ae401f611ac2dfa71670f034d726e857` (2026-10-08)\
**Related:** [Production Security Gates](../architecture/production-security-gates.md),
[Tenant Isolation](../architecture/tenant-isolation.md),
[Decision Register](../privacy/decision-register.md),
[JJ Review Packet](../privacy/jj-decision-review-packet.md),
[Delivery Plan](delivery-plan.md)

## Post-closeout roadmap amendment — 2026-10-09

M1 was completed and verified under the earlier plan, in which live AWS/Staging
activation belonged to M3. This document originally recorded that M3 deferral.

After M1 completion, delivery sequencing was refined
([Delivery Plan](delivery-plan.md)):

- **M2** — Workflow Platform: local + CI
- **M3** — Workflow Proof: local + CI
- **M4** — Intelligence Layer: local + CI
- **M5** — AWS activation, Staging, cloud hardening and Production release

The current-plan statements below (§1, §2, §7, §10, §11 and §12) now name M5
for AWS and cloud activation. The original wording is in Git history at
`7449a4b`. Verification results, commit SHAs and CI evidence are unchanged.

This changes delivery timing only. It does not invalidate the M1 architecture,
implementation, security controls, tests or acceptance evidence. **M1 remains
Done.**

## 1. Purpose

M1 establishes the security foundation that every HeroOS workflow builds on:
who a user is, which Company they may act for, and that one Company's HR data
(records and files) can never reach another Company. It also covers safe logging,
recoverable data and recorded privacy decisions. M1 is **local-first,
cloud-ready, cloud-late**: controls are proven locally and in CI; AWS activation
is M5.

This document records the M1-09 verification of current `main`. It adds no
functionality.

## 2. JJ milestone summary

HeroOS now has the secure foundation the product will be built on:

1. **Secure Company (tenant) foundation.** Every customer's data belongs to
   exactly one Company, and the Company is the security boundary.
2. **Sign-in and membership checks on the server.** Every protected request must
   carry a verified identity, and access to a Company is granted only by a HeroOS
   Membership checked on the server. What the browser claims never grants access.
3. **Core business records.** Companies, Company Blueprints, Case Subjects
   (employees) and Cases are stored in a persistent database with controlled
   schema changes.
4. **Two independent layers of tenant protection.** Application code is scoped
   to one Company, and the database itself (PostgreSQL Row-Level Security) refuses
   to show or change another Company's rows even if application code were wrong.
5. **Private file storage boundary.** Files are stored per Company, under
   server-generated names. They are never publicly served and never reachable
   across Companies.
6. **Privacy-safe logging and errors.** Logs record what happened, not the HR
   content, tokens or secrets involved. Users see generic error messages.
7. **Proven database recovery.** A backup → restore → security re-check runs
   automatically on every change.
8. **Controlled Security & Privacy Decision Register.** 22 open policy questions
   (retention, deletion, backups, AI, vendors, residency) are recorded with
   options and are awaiting JJ and legal input. None has been assumed.
9. **A stable base for M2 workflows.** New workflow features plug into the
   existing security pattern without redesign.

**What is not claimed.** HeroOS is not yet running in AWS. There is no live
Staging environment, no real Cognito sign-in and no customer-facing product
screens yet. Cloud activation happens in **M5**, after the M5-blocking decisions
in the register are made. Unresolved legal/privacy decisions stay visible in the
register. M2 can proceed within those boundaries. In particular, M2 must not offer
user-facing deletion until PRIV-020 is decided.

## 3. M1-01 to M1-08 on `main`

| Issue | Scope | On `main` | CI on merge |
| --- | --- | --- | --- |
| M1-01 | V1 architecture & security baseline (ADR-001–007, architecture docs) | `66afc1b` | (pre-CI) |
| M1-02 | Repository & engineering quality gates (PR #1) | `796a302` | success |
| M1-03 | Deployment foundation, Terraform scaffold (no resources, no backend) (PR #2) | `bf7fc92` | success |
| M1-04 | Database & core data: Company, User, Membership, Blueprint, Case Subject, Case (PR #3) | `cc4c455` | success |
| M1-05 | Authentication & Membership authorization (PR #4) | `a9e56f8` | success |
| M1-06 | Tenant isolation: scoped repositories, tenant context, RLS (PR #5) | `5cccb5e` | success |
| M1-07 | Private storage, secrets, logging, backup/restore (PR #6) | `5551675` | success |
| M1-08 | Security & Privacy Decision Register (PR #7) | `43eb33e` | success |

## 4. Engineering gates (current `main`, run locally for M1-09)

| Gate | Result |
| --- | --- |
| `make check` | PASS. Web lint/typecheck/test (1)/build. API ruff, format (97 files), mypy (51 files), pytest 351 passed, 155 skipped, 1 warning |
| `make migration-check` | PASS. base → head → base → head with schema and RLS assertions on a disposable database |
| `make tenant-isolation-check` | PASS. 131 passed on real PostgreSQL 16 |
| `make backup-restore-check` | PASS. 24 passed: data, schema, RLS, grants, isolation after restore, artifact cleanup |
| `make privacy-decision-check` | PASS. Self-test 15 cases. Register: 22 decisions |
| `docker compose config` | valid |
| `git diff --check` | clean |

The 155 pytest skips under `make check` are the PostgreSQL-only suites
(`tests/tenant_isolation`, `tests/recovery`). They run in full under
`make tenant-isolation-check` and `make backup-restore-check`.

## 5. CI: configured vs. verified on GitHub

`.github/workflows/ci.yml` runs on every pull request and every push to `main`.
It defines six jobs: **Web**, **API**, **Containers**, **Tenant Isolation**,
**Backup & Restore** and **Privacy Decisions**.

**Verified on GitHub** with `gh` (read-only): run
[37820014040](https://github.com/HeroOS-HQ/heroos-app/actions/runs/37820014040),
the `push` to `main` at `43eb33e`, completed with all six jobs `success`. Every
M1 merge to `main` (M1-02 to M1-08) has a successful push run.

## 6. Local runtime

`make db-setup`, `make local-up` and `make local-ps` succeed. `db`, `api` and
`web` are all `healthy`. `GET http://127.0.0.1:8001/health` returns
`{"status":"ok"}`, and the web app on `http://127.0.0.1:3002/` returns HTTP 200.
The API container runs `uvicorn … --no-access-log` and emits only structured
JSON (`request_completed` with route template, status and request ID).

## 7. Verification summary by area

**Authentication & authorization (M1-05).** Tests cover the following:
- Missing, malformed, unsigned, expired or wrongly-issued tokens are rejected (401).
- A verified identity maps to a User only through `users.identity_subject`.
- An unknown User and a missing Membership are denied with indistinguishable 403s.
- Company IDs in claims, headers or query strings never authorize, and every Company in the path is re-authorized server-side.
- Membership in Company A grants no access to Company B.
- `AuthenticatedCompanyContext` is the only trusted Company context.
- The development provider is refused outside `HEROOS_ENV=development`.
- Cognito verification (RS256, `iss`, `exp`, `token_use=access`, `client_id`) is tested against a locally generated JWKS.

No Cognito pool exists, and live Cognito is not claimed.

**Tenant isolation (M1-06).** Layer 1: repositories take a `CompanyScope`.
Layer 2: a transaction-local `heroos.company_id` setting is read by
`heroos_current_company_id()`, and a single `tenant_isolation` RLS policy
(`USING` and `WITH CHECK`) covers `companies`, `memberships`, `company_blueprints`,
`case_subjects` and `cases`. The API connects as `heroos_app`, a member of
`heroos_app_runtime`: NOSUPERUSER, NOBYPASSRLS, owns no tables. A startup guard
refuses privileged roles. On real PostgreSQL the suite proves the following:
- Missing or malformed context shows nothing.
- Cross-company reads, writes, and moves of rows to another Company fail.
- Guessed IDs fail under RLS alone.
- Pool reuse after commit, rollback, a failed statement or a mid-transaction close does not leak context.
- Composite keys stop a Case from referencing another Company's Case Subject.

**Private storage & operational security (M1-07).** `PrivateObjectService`
requires a `CompanyScope` and accepts no caller-supplied Company, key or path.
- **Local provider.** Development-only. It is refused in staging/production and refuses a root inside the source tree or a web-served directory. It uses 0700 directories and 0600 files, writes each object once, and rejects symlinks and tampered keys.
- **No public file routes.** The application exposes no static or file routes, and a foreign object ID behaves exactly like a missing one.
- **S3.** The `s3` provider is refused until its adapter exists (M5).
- **Secrets and configuration.** Secrets are `SecretStr` and configuration-driven. Database URLs are never rendered.
- **Logs and errors.** Logs are allowlisted JSON with SQL/HTTP-client loggers pinned to WARNING. Unhandled errors return a generic 500 with an `error_id`.
- **Leakage tests.** These run at DEBUG.

**Backup & recovery (M1-07).** `make backup-restore-check` performs a logical
backup → restore → verification on disposable databases. After restore it
re-checks schema, RLS, grants, the runtime-role startup guard and cross-tenant
isolation. It never touches the development database. RDS automated backups/PITR
are M5.

**Privacy & governance (M1-08).** The single authoritative
[Decision Register](../privacy/decision-register.md) holds PRIV-001 to PRIV-022:
unique, contiguous and validated in CI. Every JJ decision is **Pending**. No
legal approval is recorded, and the validator rejects approved, legally-confirmed
or implemented states without evidence. PRIV-022 (HeroOS data-protection role) is
**Pending Analysis** and classifies nothing. The
[JJ Review Packet](../privacy/jj-decision-review-packet.md) separates M2-blocking,
external-AI (M4), cloud/Production (M5) and safely-pending items.

## 8. Deletion boundary (PRIV-020)

The only HTTP route in the application is `GET /health`. Company-scoped internal
delete primitives exist (`delete_case`, `delete_case_subject`,
`delete_company_blueprint`, `PrivateObjectService.delete`). They are exercised only
by test-built apps, and no product route exposes them. They are kept because
PRIV-020 records them as the technical foundation. **M2 must not expose
user-facing deletion of Cases, Case Subjects, documents or Companies until
PRIV-020 is decided.** This is a governance boundary, not a code defect.

## 9. M2 readiness

**Conclusion: M2 may begin.** Authentication, Membership authorization, Company
context, tenant isolation, the core data model, the private object boundary,
logging/error handling and decision governance need no redesign.

New M2 private entities (workflow instances, facts, decisions, audit events,
document metadata) adopt the existing contract in
[Tenant Isolation §9](../architecture/tenant-isolation.md):

```text
company_id (non-null, FK, composite same-Company keys)
  -> Company-scoped repository (CompanyScope)
  -> trusted Company context (AuthenticatedCompanyContext / CompanyDb)
  -> transaction-local PostgreSQL tenant context (heroos.company_id)
  -> RLS tenant_isolation policy, created in the table's migration
  -> cross-tenant read/write tests in tests/tenant_isolation
```

`test_every_table_has_rls_unless_explicitly_exempt` fails for any new table without
RLS, so a missed step is caught in CI rather than in review.

**M2 boundaries (not blockers to starting M2):**
- No user-facing deletion until PRIV-020 is decided. Retention and deletion behavior follows PRIV-001 to PRIV-004, PRIV-008 and PRIV-016.
- No production customer data and no external AI processing (PRIV-009 to PRIV-012, PRIV-014, PRIV-021).
- New loggers and log fields follow [Observability §6](../architecture/observability.md).

## 10. M5 deferral (live cloud activation)

Originally recorded as the M3 deferral; moved to M5 by the post-closeout
roadmap amendment above.

None of the following exists or is claimed. Each is owned by M5 and specified in
[Production Security Gates](../architecture/production-security-gates.md):
- AWS account/service activation (`me-central-1`) and live Staging
- ECS/Fargate
- RDS for PostgreSQL with encryption, TLS, automated backups/PITR and a real restore drill
- RDS review of the runtime-role grants and ownership
- Cognito User Pool/App Client and frontend production login
- S3 adapter and private bucket (Block Public Access, encryption, versioning per PRIV-019)
- Secrets Manager
- CloudWatch logs/alarms
- ACM/ALB HTTPS
- Deployed revision traceability

**M5 blockers (governance):**
- PRIV-006, PRIV-007, PRIV-013, PRIV-014, PRIV-017, PRIV-019 and PRIV-022.
- Confirmation of the development VPS hosting provider ([Service Inventory](../privacy/third-party-service-inventory.md)).

**Not an M5-only gate:** PRIV-009 to PRIV-012, PRIV-014 and PRIV-021 must be
decided before any external AI provider receives identifiable or customer data,
which may happen in M4 (Intelligence Layer). PRIV-020 remains an M2 boundary (§8).

## 11. Known technical debt (non-blocking)

| Item | Evidence | Note |
| --- | --- | --- |
| `StarletteDeprecationWarning` (httpx with `starlette.testclient`) | pytest warning under `make check` | Test-only. Address on the next FastAPI/Starlette upgrade |
| Cognito sign-out/disable takes effect at access-token expiry | `app/auth/providers/cognito.py` verifies JWTs statelessly | Removing a HeroOS User or Membership is immediate. Choose token lifetime at M5 |
| One issuer per environment | Users map by `identity_subject` only; one Cognito issuer configured; dev issuer refused outside development | Multiple pools/IdP federation would need issuer-qualified mapping |
| JWKS availability | [Authentication §4.1](../architecture/authentication.md): fetch failure → 401 (1 h cache) | Fails closed. Cognito JWKS reachability is an M5 availability dependency |
| Library log records keep their message text | [Observability §5](../architecture/observability.md) residual risk | Every new dependency needs a logging review (`QUIETED_LOGGERS`) |
| Error after response started | `app/observability/middleware.py`; `test_exception_after_response_started_is_logged_not_reraised` | Connection is closed (truncated response) and the event is logged. No streaming routes exist yet |
| RLS/runtime role not exercised on RDS | [Tenant Isolation §10](../architecture/tenant-isolation.md) | Re-review grants/ownership at RDS provisioning (M5) |

## 12. M1 blocker assessment

| Finding | Classification |
| --- | --- |
| Any failing gate, isolation regression or exposed cross-tenant/deletion path | **None found** |
| Items in §11 | Non-blocking technical debt |
| PRIV-001 to PRIV-022 (all JJ Pending), incl. PRIV-020 and PRIV-022 | Pending governance decision |
| Live AWS, Cognito, RDS, S3, Secrets Manager, CloudWatch, ACM/ALB | Deferred to M5 (originally M3; see the post-closeout amendment) |

**No BLOCKER remains. M1 can be marked Done.**
