# ADR-004 — Data Architecture and Multi-Tenant Isolation

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS V1 is a multi-tenant SaaS application that will process private
company, employee and HR case information.

The data model must support:

- multiple HeroOS companies
- users belonging to one or more companies
- Company Blueprint data
- employees / case subjects
- HR cases
- versioned workflow instances
- structured facts
- Condition evaluations
- human decisions
- documents
- audit events
- future workflow expansion

The architecture must prevent one company from accessing another company's
data.

Tenant isolation must not depend only on frontend behavior or on developers
remembering to manually add arbitrary `company_id` filters.

PostgreSQL is the authoritative application database.

---

## Decision

HeroOS V1 will use Amazon RDS for PostgreSQL as the authoritative relational
database.

The tenant root is the HeroOS **Company**.

Tenant-private records must have an explicit ownership path to a Company.

Application authorization is mandatory.

PostgreSQL Row Level Security (RLS) will be used as defense in depth for
appropriate tenant-owned tables.

RLS does not replace backend authentication, Company Membership validation or
application authorization.

---

## Tenant Root

The canonical tenant entity is:

```text
Company
```

Every tenant-private record has an explicit `company_id` referencing `companies`.
`users` is a global identity table and is not tenant-owned. Access to a Company
comes only from a `memberships` row.

---

## Implementation (M1-06)

Tenant isolation is implemented as described in
[Tenant Isolation](../architecture/tenant-isolation.md):

- Company-scoped repositories (`CompanyScope`) built only from the
  Membership-derived `AuthenticatedCompanyContext`.
- A transaction-local PostgreSQL tenant context (`set_config('heroos.company_id',
  ..., true)`). Session-level `SET` is forbidden.
- PostgreSQL RLS on `companies`, `memberships`, `company_blueprints`,
  `case_subjects` and `cases`, with one permissive `FOR ALL` policy per table
  (`USING` and `WITH CHECK`).
- The API runs as a runtime role that is not superuser, has no `BYPASSRLS` and
  owns no tables. Migrations run as a separate migration/admin role.
- A real-PostgreSQL cross-tenant security suite runs in CI.

Future tenant-private tables, including M2 workflow entities, must follow the
contract in [Tenant Isolation §9](../architecture/tenant-isolation.md#9-contract-for-future-private-entities-m2-and-later).
