# HeroOS Tenant Isolation

**Status:** Implemented (M1-06). Proven on local and CI PostgreSQL 16. Not yet tested on Amazon RDS\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security\
**Issue:** M1-06 — Enforce tenant isolation & cross-tenant security tests\
**Related:** [ADR-004](../decisions/ADR-004-data-and-tenancy.md),
[Authentication](authentication.md), [Security Boundaries](security-boundaries.md)

## 1. Summary

**Company is the tenant boundary.** Company A must never read or change
Company B's private relational data, even if IDs are guessed or manipulated, an
application query is accidentally too broad, or a pooled connection is reused.

Isolation is enforced in two independent layers. Each one is tested alone.

```text
Verified credential                         (M1-05, 401 on failure)
        ↓
AuthenticatedCompanyContext                 (M1-05 Membership, 403 on failure)
        ↓
CompanyScope + Company-scoped repositories  layer 1: application filter
        ↓
transaction-local heroos.company_id         set_config(..., true)
        ↓
runtime DB role heroos_app                  not superuser, no BYPASSRLS, owns nothing
        ↓
PostgreSQL Row-Level Security               layer 2: tenant_isolation policies
        ↓
companies, memberships, company_blueprints, case_subjects, cases,
workflow_instances, workflow_submissions, case_facts (M2-01)
```

A client-supplied `company_id` (path, query, header, body, token claim) only
identifies the requested tenant. It never authorizes. Only a server-side
Membership does, and that produces `AuthenticatedCompanyContext`, the only
trusted source of the Company used for data access.

Frontend filtering is never a security boundary.

## 2. Layer 1: Company-scoped data access

`app/tenancy/` and `app/repositories/`.

- `CompanyScope(session, company_id)` is built by `open_company_scope(session,
  context)` from an `AuthenticatedCompanyContext`. It sets the database tenant
  context and carries the same Company for the application filter.
- Routes depend on `CompanyDb` (`app/tenancy/dependencies.py`):

  ```python
  @router.get("/companies/{company_id}/cases/{case_id}")
  def get_case(case_id: UUID, scope: CompanyDb) -> ...:
      case = cases.get_case(scope, case_id)
      if case is None:
          raise HTTPException(404, "Not found")
  ```

- Every repository function takes a `CompanyScope` and filters by
  `scope.company_id` in addition to any resource ID. Conceptually it is
  `get_case(company_id, case_id)`, never `get_case(case_id)`. Update and delete
  first load the row through the same scoped lookup.
- `company_id` is always taken from the scope. No repository function accepts or
  changes it. Company and Company Blueprint functions can only address the
  scope's own row.
- References are checked in the same Company: a Case can only point at a
  CaseSubject of its own Company (`ResourceNotFoundError` otherwise; the
  composite `(company_id, subject_id)` foreign key enforces it again in the
  database).
- Repositories flush but never commit. Handlers call `scope.commit()`, which
  commits and re-binds the next transaction to the same Company. A plain
  `session.commit()` ends the tenant context, so later ORM refreshes see no rows
  (fail closed).

## 3. Transaction-local tenant context

`app/tenancy/context.py`.

```sql
SELECT set_config('heroos.company_id', '<company uuid>', true)  -- true = transaction-local
```

- `set_tenant_context(session, company_id)` accepts only a non-nil `uuid.UUID`.
  Strings, `None` and the nil UUID are rejected before any SQL is sent. The
  value is a bound parameter.
- The value disappears on commit and on rollback. When SQLAlchemy returns a
  connection to the pool it rolls back as well, so the context also disappears
  if a request ends abnormally.
- A transaction serves one Company. Re-binding it to a different Company raises
  `TenantContextError`.
- **Session-level `SET heroos.company_id = ...` (or `set_config(..., false)`) is
  forbidden.** It survives commit and pool return, so the next request on that
  physical connection would run as the previous Company. The suite contains a
  control test showing exactly this leak.

There is no hidden SQLAlchemy event. Setting the context is an explicit call,
made only by `open_company_scope` and the Membership bootstrap (section 6).

## 4. Layer 2: PostgreSQL Row-Level Security

Migration `97d4200fe7a2_add_tenant_row_level_security.py`.

| Table | Owner column | Policy expression (USING and WITH CHECK) |
| --- | --- | --- |
| `companies` | `id` | `id = heroos_current_company_id()` |
| `memberships` | `company_id` | `company_id = heroos_current_company_id()` |
| `company_blueprints` | `company_id` | `company_id = heroos_current_company_id()` |
| `case_subjects` | `company_id` | `company_id = heroos_current_company_id()` |
| `cases` | `company_id` | `company_id = heroos_current_company_id()` |
| `workflow_instances`, `workflow_submissions`, `case_facts` (M2-01, migration D1) | `company_id` | `company_id = heroos_current_company_id()` |

- Each table has exactly **one** permissive `FOR ALL` policy, `tenant_isolation`,
  for `PUBLIC`. It covers SELECT, INSERT, UPDATE and DELETE. Because PostgreSQL
  ORs permissive policies together, a second policy could only widen access, so
  there is none. A test fails if a second policy appears.
- `USING` hides other Companies' rows from SELECT, UPDATE and DELETE.
  `WITH CHECK` rejects inserting a row for another Company and moving a row to
  another Company (`UPDATE ... SET company_id = <B>`).
- `heroos_current_company_id()` is a `STABLE`, `SECURITY INVOKER` SQL function:
  `NULLIF(current_setting('heroos.company_id', true), '')::uuid`. An unset or
  empty setting yields `NULL`, and `company_id = NULL` matches no row. A
  malformed value raises a cast error. Neither case ever widens visibility.
- `users` and `user_identities` have no tenant policy. They are global identity
  tables with no `company_id` (ADR-008), read before any Company is known to map
  a verified identity to a HeroOS User. Adding a fake `company_id` would be
  wrong, because a User can belong to several Companies. They hold no personal
  data except the pseudonymous external `subject`. Instead of a tenant policy
  they carry *lifecycle* policies: the runtime role may only SELECT active rows;
  the identity operator group (`heroos_identity_operator`) manages them. No
  tenant repository exposes them.
- `memberships` also carries a RESTRICTIVE `lifecycle_active` policy for the
  runtime role (`status = 'active'`): it can only narrow the tenant policy, never
  widen it. Revoked Memberships are invisible to the API whatever code runs.
- `membership_events`, `company_events` and `company_registrations`
  (tenant-owned audit and registration records, M1-10B/M1-10C) have the
  standard `tenant_isolation` policy; `identity_events` (global audit) has RLS
  with no policy at all. None is granted to the runtime or operator role: only
  owner-run triggers and the registration function write them.
- `TRUNCATE` is not subject to RLS and is never granted to the runtime role.
- RLS is not `FORCE`d. The runtime role never owns tables, and the owner
  (migration/admin) role must still be able to run data migrations without a
  tenant context.

### Missing and invalid context

| Situation | Result |
| --- | --- |
| No tenant context | Every tenant table looks empty. INSERT fails (`42501`). UPDATE and DELETE affect 0 rows |
| Non-existent Company UUID | No rows. INSERT fails the Company foreign key |
| Malformed raw setting | Query error (`22P02`). No rows |
| Invalid value passed to `set_tenant_context` | `TenantContextError` before any SQL |
| `/companies/<not-a-uuid>/...` | 422 (request validation) |
| `/companies/00000000-0000-0000-0000-000000000000/...` | 403, the same as any unknown Company |

There is no default tenant and no fallback to all tenants.

## 5. Database roles

| Role | Kind | Used by | Privileges |
| --- | --- | --- | --- |
| `heroos` (local) / RDS migration role | migration/admin, schema owner | Alembic (`MIGRATION_DATABASE_URL`) | DDL, owns tables and policies. Never used by the API |
| `heroos_app_runtime` | `NOLOGIN` privilege role, created by the migration | — | SELECT/INSERT/UPDATE/DELETE on `case_subjects`, `cases`; SELECT/UPDATE on `companies` (no INSERT/DELETE since C1: Companies are created only through registration); SELECT/DELETE and column-level INSERT/UPDATE on `company_blueprints` (every column except the four jurisdiction-confirmation columns); SELECT only on `memberships`, `users`, `user_identities` (ADR-008); EXECUTE on `heroos_register_company` and `heroos_identity_companies` (ADR-010). Since D1 (M2-01): SELECT/INSERT on `workflow_submissions` and `case_facts`, SELECT/INSERT and column-level UPDATE (`revision`, `updated_at`) on `workflow_instances`: append-only, no DELETE. Nothing on the audit or registration tables or `alembic_version`. No TRUNCATE |
| `heroos_identity_operator` | `NOLOGIN` group, created by migration B1a | identity operator CLI (ADR-008) | From B1b: SELECT/INSERT and column-level UPDATE (`status`, `revoked_at`/`suspended_at`, `updated_at`) on `users`, `user_identities`, `memberships` (RLS); SELECT (`id`) on `companies`. From C1: INSERT (`id`, `name`) on `companies`, INSERT (`id`, `company_id`), SELECT of the licensing and confirmation columns and UPDATE of the confirmation columns on `company_blueprints`, UPDATE (`role`) on `memberships` (all under RLS). Nothing on case data, the Blueprint business profile, audit tables or `alembic_version`. No DELETE, no TRUNCATE. Never a member of `heroos_app_runtime` |
| `heroos_app` | login role, member of `heroos_app_runtime` | the API (`DATABASE_URL`) | inherits the above. `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`, owns nothing |

- Superusers, `BYPASSRLS` roles and table owners skip RLS. The API therefore
  **refuses to start** (`app/db/runtime_role.py`, run from the FastAPI lifespan)
  if its role is, or can `SET ROLE` to, a superuser, `BYPASSRLS` or `CREATEROLE`
  role, or owns any table in `public`.
- The migration creates only the passwordless `NOLOGIN` role and grants. No
  credential is ever in a migration. Downgrade revokes grants and drops
  policies and the helper function. The role itself is cluster-wide (shared by
  every database on the server) and is left in place.
- Grants are explicit per table. There are no default privileges, so a new table
  is inaccessible to the API until its migration grants access. That makes the
  privilege review part of the future-entity contract (section 9).

### Local setup

`DATABASE_URL` and `MIGRATION_DATABASE_URL` live only in the untracked root
`.env`, generated by `make env-init`; there are no built-in defaults
([Database Credentials](../operations/database-credentials.md)).

```bash
make env-init          # once: generated passwords in .env (0600)
make db-setup          # = make migrate + make db-runtime-role
make local-up          # starts db, runs db-setup, then builds and starts api and web
```

`make db-runtime-role` (`apps/api/scripts/bootstrap_runtime_role.py`) creates or
updates the `DATABASE_URL` login role with its password, removes any dangerous
attributes, grants `heroos_app_runtime` and then verifies the result from the
catalog. It is idempotent, so it works on new and existing Docker volumes, and
it does not depend on `/docker-entrypoint-initdb.d`. It refuses non-local hosts
and refuses to use the admin role as the runtime role. The password must be a
generated one (64 lowercase hex characters) and is sent only as a client-side
SCRAM-SHA-256 verifier, never as plaintext SQL. Because roles are cluster-wide,
it refuses to manage the shared `heroos_app` role from a disposable `*_test`
database.

The verification suites never touch `heroos_app`. Each run bootstraps its own
disposable login role (`heroos_app_t_<8 hex>`, random password, member of
`heroos_app_runtime`), runs every runtime assertion as that role and drops it
afterwards. The scripts fingerprint the `heroos_app` credential and attributes
before the run and fail if they changed.

Deployed environments (M5) must provision their runtime login role through
deployment configuration with a secret-managed password, as a member of
`heroos_app_runtime`. The startup guard enforces the same properties there.

## 6. Membership authorization bootstrap

`memberships` is tenant-protected, but a Membership lookup is what creates
`AuthenticatedCompanyContext`. `authorize_company` (`app/auth/service.py`)
resolves this without any bypass:

```text
resolve_user           SELECT user_identities JOIN users            (no tenant context; global tables,
                       WHERE issuer = ... AND subject = ...        active rows only, ADR-008)
        ↓
authorize_company
  set_tenant_context(requested company_id)     candidate scope, NOT authorization
  SELECT memberships WHERE user_id = <user> AND company_id = <requested>
  ROLLBACK                                     candidate scope discarded, success or failure
        ↓
Membership found  -> AuthenticatedCompanyContext(company_id from the Membership row)
no Membership     -> AuthorizationError -> 403
        ↓
open_company_scope(context)                    new transaction, trusted scope
```

**Setting a candidate database scope is not authorization. Membership
existence is authorization.**

- The candidate scope exposes only the requested Company's rows, and only to
  this one query, which is further restricted to the authenticated User.
- No domain query runs under the candidate scope, and the transaction is rolled
  back before `authorize_company` returns.
- There is no `BYPASSRLS`, no `SECURITY DEFINER` function, no globally readable
  Membership and no admin connection in the request path.
- M1-05 semantics are unchanged: missing or invalid credential → 401; unknown
  User, missing Membership, other Company, non-existent Company or nil UUID →
  the same 403.

## 7. Error semantics

| Request | Response |
| --- | --- |
| `/companies/{B}/...` by a member of A only | `403 {"detail": "Forbidden"}`, identical to a non-existent Company |
| `/companies/{A}/cases/{case of B}` by a member of A | `404 {"detail": "Not found"}`, identical to a random UUID |
| Create or reference using another Company's resource | `404`, and the row is not created |

Responses never reveal whether another Company's resource exists, and never
include SQL, policy names, role names or credentials. Logs record fixed reasons
and the requested Company ID only (see [Authentication §7](authentication.md)).

## 8. Test strategy and evidence

| Command | Database | What it proves |
| --- | --- | --- |
| `make check` | none (SQLite stand-ins) | Unit and quality gates: context validation, bootstrap-script refusals, M1-05 auth. The PostgreSQL suite is skipped |
| `make migration-check` | disposable `heroos_migration_test` | base → head → base → head; RLS tables, policies and runtime role exist; downgrade removes them |
| `make tenant-isolation-check` | disposable `heroos_tenant_isolation_test` | 131 real-PostgreSQL security tests as the runtime role |
| `make backup-restore-check` (M1-07) | disposable `heroos_backup_source_test` / `heroos_backup_restore_test` | a logical backup restores with identical data, RLS, policies, grants and runtime-role isolation ([Backup and Recovery](backup-and-recovery.md)) |

`make tenant-isolation-check` (`apps/api/tests/tenant_isolation/`) creates the
database, migrates it as admin, bootstraps the runtime role, seeds Company A and
Company B for every test, and drops the database afterwards (also on failure).
It refuses any database name other than `*_tenant_isolation_test`.

| File | Proves |
| --- | --- |
| `test_runtime_role.py` | From the catalog: the runtime role is not superuser, BYPASSRLS, CREATEROLE or CREATEDB, cannot reach such a role, owns no table, and has exactly the expected grants (no TRUNCATE). It cannot create tables, disable RLS, drop or add policies, replace the context function, `SET ROLE` admin or read `alembic_version`. `row_security=off` errors. Every table except `alembic_version` has RLS. One permissive `FOR ALL` policy per tenant table; the only other policies are the listed lifecycle policies (ADR-008). The startup guard accepts the runtime role and rejects admin and identity-operator logins |
| `test_role_separation.py`, `test_identity_provisioning.py`, `test_identity_migration.py`, `test_operator_cli.py` | M1-10B (ADR-008): the runtime role cannot provision, bind, reassign, suspend, revoke or read audit; the operator cannot read HR data, delete, rewrite bindings or forge audit; lifecycle is denied on the next request; B1a/B1b compatibility with the previous API and history-based downgrade refusal |
| `test_company_registration.py`, `test_founder_registration.py`, `test_company_roles.py`, `test_company_blueprint.py`, `test_company_migration.py` | M1-10C (ADR-010): operator and founder registration are atomic, idempotent and concurrency-safe, never reach an existing Company and are audited; only `company_admin` updates the Blueprint, roles never come from claims or bodies and are re-checked in the write transaction; licensing answers never resolve a jurisdiction; the API role cannot create Companies, change roles or write the confirmation; C1 keeps the M1-10B API working and refuses to roll back once history exists |
| `test_tenant_context.py` | Missing, stale, malformed and invalid context fail closed. Context is transaction-local across commit and rollback. A transaction cannot switch Company. A plain commit drops context even for ORM refreshes |
| `test_cross_tenant_reads.py` | A↔B direct lookups, lists and guessed IDs, each proven three ways: repositories with RLS, RLS alone (unfiltered queries) and the repository filter alone (admin session that bypasses RLS) |
| `test_cross_tenant_writes.py` | Cross-Company create (all 5 tables), update, delete and re-parenting are blocked by repositories and by RLS, each on its own. `WITH CHECK` is also proven alone, using INSERT without `RETURNING` and UPDATE without `WHERE`; otherwise PostgreSQL applies `USING` to the new row as well. Same-Company writes succeed |
| `test_membership_bootstrap.py` | Candidate-scope bootstrap allows members, denies everyone else and leaves no scope or visible data behind. Memberships are not globally readable |
| `test_connection_pool.py` | Pool of one connection, same `pg_backend_pid()`. Context is gone after commit, rollback, an abandoned session and a failed statement. 20 alternating A/B requests. A session-level `SET` control shows the leak the design prevents |
| `test_workflow_cases.py` | M2-01: workflow instances, submissions and facts isolated three ways (repositories with RLS, RLS alone, repository filter alone); Company-qualified foreign keys refuse cross-Company and cross-instance links; the API role can only append and cannot delete a Case with a workflow; the operator cannot read workflow data; row-locked saves, compare-and-set, concurrent saves and concurrent idempotent creation on real PostgreSQL, with a deterministic regression test for the replay race found in CI; the production routes (administrator-only reads and writes, 403/404, demotion refused in the request's transaction, Disciplinary records hidden from members in the generic Case routes) |
| `test_http_isolation.py` | Test-only routes on the real dependency chain: guessed IDs → 404, other Company → 403, write attempts change nothing, client `company_id` in the body is ignored, M1-05 401/403 semantics hold under RLS, no context left on the pooled connection |

CI runs `make migration-check` and `make tenant-isolation-check` in the
**Tenant Isolation** job against the Compose PostgreSQL 16 service, with
per-run generated credentials (`make env-init`, masked), no AWS and no stored
secrets.

Mutation checks during M1-06 showed that the suite fails when any of these is
introduced: the repository filter removed, RLS not enabled on a table, the
runtime role given `BYPASSRLS`, `set_config(..., false)` used instead of
transaction-local scope, `WITH CHECK (true)`, the candidate scope not
discarded, an extra permissive policy, or `TRUNCATE` granted.

## 9. Contract for future private entities (M2 and later)

Every new tenant-private relational table (for example M2 workflow instances,
facts, decisions or audit events) must have:

1. an explicit, non-null `company_id`;
2. a foreign key to `companies` (and composite `(company_id, <id>)` keys for
   same-Company references between tenant tables);
3. Company-scoped repository functions that take a `CompanyScope`;
4. access only inside a transaction-local tenant context (`CompanyDb` /
   `open_company_scope`);
5. RLS enabled, with a single `tenant_isolation` policy (`USING` and `WITH
   CHECK` on `company_id = heroos_current_company_id()`), created in the same
   migration as the table;
6. a privilege review: explicit grants to `heroos_app_runtime`, least privilege,
   never TRUNCATE;
7. cross-tenant read and write tests in `tests/tenant_isolation`.

`test_every_table_has_rls_unless_explicitly_exempt` fails for any new table
without RLS unless it is added to the exemption list with a documented reason.
Global, non-tenant tables (like `users` and `user_identities`, ADR-008) need that
explicit justification and their own role-scoped RLS policies.

Retention and deletion behavior of new entities (delete routes, soft-delete
columns, cascades from Cases) is not a technical default. It follows the
[decision register](../privacy/decision-register.md), in particular PRIV-020.

## 10. Out of scope

- Private documents and object storage are secured separately in **M1-07**
  ([Private Object Storage](private-object-storage.md)). RLS protects relational
  rows only. A future document-metadata table must follow section 9.
- Workflow entities and workflow authorization are **M2**. M2-01 adopted
  section 9 without redesign for `workflow_instances`, `workflow_submissions`
  and `case_facts` ([Workflow Case Foundation](workflow-foundation.md)).
- Company roles are minimal (`company_admin`, `member`; M1-10C, ADR-010).
  Fine-grained permissions inside a Company are not part of V1.
- Amazon RDS, Terraform and deployed runtime-role provisioning are not part of
  M1-06. Nothing here has contacted AWS, and the design has not yet been
  exercised on RDS (where the master user is not a superuser, so grants and
  ownership must be reviewed again at provisioning time).
