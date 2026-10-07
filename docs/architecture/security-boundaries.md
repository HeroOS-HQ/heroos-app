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
Infrastructure configuration