# HeroOS V1 Security Boundaries

**Status:** Draft architecture baseline  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline  
**Last updated:** 2026-10-08

## 1. Purpose

This document defines the principal security boundaries and security
invariants for HeroOS V1.

HeroOS processes company, employee and HR case information that must remain
private to the authorized company.

The primary security objective is therefore:

> An authenticated user may access only the HeroOS resources explicitly
> authorized through their valid company membership.

Authentication alone is not authorization.

A resource identifier alone is not authorization.

Frontend visibility is not authorization.

Security-sensitive decisions must be enforced by the backend.

---

## 2. Security Principles

HeroOS V1 follows these security principles.

### 2.1 Fail Closed

When identity, company membership, tenant ownership, permissions or resource
authorization cannot be established safely, access must be denied.

HeroOS must not infer access from incomplete information.

### 2.2 Least Privilege

Applications, users and infrastructure components should receive only the
permissions required to perform their responsibilities.

### 2.3 Explicit Tenant Isolation

Every private HeroOS resource must belong to an identifiable tenant or have
an explicit relationship to a tenant-owned resource.

Cross-tenant access must be prevented at the backend.

### 2.4 Backend Enforcement

Authorization and business-rule enforcement belong in trusted backend
services.

The browser may improve the user experience by hiding inaccessible actions,
but frontend behavior is not a security control.

### 2.5 Defense in Depth

Security should not depend on one control alone.

Where practical, HeroOS combines:

- managed authentication
- server-side authorization
- tenant-scoped data access
- database constraints
- private object storage
- infrastructure access controls
- encryption
- automated negative tests
- audit events
- monitoring

### 2.6 Minimize Sensitive Data Exposure

Sensitive HR information should only be exposed to systems and personnel that
require it.

Logs, telemetry, AI prompts and support tooling should receive the minimum
information necessary.

---

## 3. Trust Boundaries

The main V1 trust boundaries are:

```text
Untrusted / External
--------------------

Customer browser
External user input
Uploaded files
External AI provider
Email recipient
Third-party integrations

        |
        v

Public HeroOS Boundary
----------------------

HTTPS entry point
Next.js web application

        |
        v

Authenticated Application Boundary
----------------------------------

FastAPI
Authentication validation
Membership resolution
Authorization
Domain services
Workflow services
Condition services
AI Gateway

        |
        v

Private Data Boundary
---------------------

PostgreSQL
Private S3
Secrets Manager
Internal AWS services
Audit data

        |
        v

Infrastructure Administration Boundary
--------------------------------------

AWS administrative access
CI/CD deployment identity
Production secrets
Database administration
Infrastructure configuration```

---

## 4. Authentication and Company Authorization Boundary

Implemented in M1-05; see
[Authentication and Company Authorization](authentication.md).

Invariants enforced by the FastAPI authentication boundary:

- A verified credential establishes identity only. It never grants Company access.
- Identity maps to a HeroOS User solely through an exact, active
  `(issuer, subject)` binding in `user_identities`, never by email or any other
  claim, and only for an active User (ADR-008).
- Company access requires a server-side lookup of an active Membership for that
  User and the requested Company. Client-supplied Company IDs, headers and token claims are
  never authorization evidence.
- Missing, malformed, unsigned, expired or invalid credentials return 401.
  Unknown Users and missing Memberships return an identical 403.
- Protected handlers receive an `AuthenticatedCompanyContext`, which exists only
  after all of the above succeed.
- Development authentication is impossible outside `HEROOS_ENV=development`:
  staging and production require Cognito and refuse to start otherwise.
- Authorization headers, bearer tokens and authentication secrets are never
  written to logs or error responses.

Live Cognito activation is M5.

---

## 5. Tenant Isolation Boundary

Implemented in M1-06; see [Tenant Isolation](tenant-isolation.md).

Company is the tenant boundary. Invariants:

- `AuthenticatedCompanyContext` (Membership-derived) is the only trusted source
  of the Company used for data access. Client-supplied Company IDs never
  authorize.
- Two independent layers, each tested alone:
  1. Company-scoped repositories (`CompanyScope`): every lookup, update and
     delete filters by the trusted Company as well as the resource ID.
  2. PostgreSQL Row-Level Security on `companies`, `memberships`,
     `company_blueprints`, `case_subjects` and `cases`, driven by a
     transaction-local `heroos.company_id` setting.
- The API connects as a runtime role that is not superuser, has no `BYPASSRLS`
  and owns no tables, and it refuses to start otherwise. Migrations use a
  separate migration/admin role.
- Missing or invalid tenant context fails closed: no rows are visible and writes
  are rejected.
- Tenant context is transaction-local and cannot leak through the connection
  pool. Session-level `SET` is forbidden.
- Another Company's resource is indistinguishable from a missing one (404
  within a Company, 403 for a Company without Membership).
- New private tenant tables (M2 onward) must follow the contract in
  [Tenant Isolation §9](tenant-isolation.md#9-contract-for-future-private-entities-m2-and-later).
- Private documents and objects are secured in M1-07 (section 6).

---

## 6. Private Object Storage Boundary

Implemented in M1-07; see [Private Object Storage](private-object-storage.md).

- Objects are accessed only through `PrivateObjectService`, which takes a trusted
  `CompanyScope`. Keys (`companies/<company uuid>/<object uuid>`) are generated
  by HeroOS. No caller supplies a Company, key, path or filename.
- Another Company's object is indistinguishable from a missing one. Knowing an
  object UUID grants nothing.
- Objects are write-once, never public, and never in a web-served directory or
  the repository. The local provider is development only (`0700`/`0600`,
  containment and symlink checks). Production uses a private S3 bucket (M5), with
  pre-signed access only after HeroOS authorization.

## 7. Secrets and Configuration

- Secrets (`HEROOS_DEV_AUTH_SECRET`, `DATABASE_URL`, `MIGRATION_DATABASE_URL`)
  are `SecretStr`. They never appear in `repr`, logs or validation errors.
- Staging and production fail closed: no development auth, no local database
  host, no migration credential in the API, no local object storage.
- No environment has a built-in database credential. Local and preview
  credentials are generated into the untracked root `.env` (`make env-init`),
  passwords reach PostgreSQL only as SCRAM-SHA-256 verifiers, and verification
  suites never manage the shared runtime role
  ([Database Credentials](../operations/database-credentials.md)).
- Production secrets come from AWS Secrets Manager (M5). Nothing real is
  committed. `.env` is excluded from Git and Docker builds.

## 8. Operational Logging and Error Boundary

Implemented in M1-07; see [Observability](observability.md).

- Structured JSON logs carry request IDs, route templates, status, duration,
  opaque Company/User IDs (after authorization) and sanitized exception metadata.
- Headers, tokens, cookies, secrets, bodies, query strings, HR content and
  exception messages are never logged. The Uvicorn access log is disabled.
- Unexpected failures return a generic 500 with `request_id` and `error_id`.
  401/403/404/422 behaviour is unchanged.

## 9. Backup and Recovery

Implemented in M1-07; see [Backup and Recovery](backup-and-recovery.md).

- Backups run as the migration/admin role, never the RLS-restricted runtime
  role. Archives are private (`0600`) and kept outside the repository.
- Restores go only into empty, non-protected databases and are validated for
  schema, RLS, policies, grants and tenant isolation before use.
- Production encryption, TLS, backups and PITR are M5 gates
  ([Production Security Gates](production-security-gates.md)).
