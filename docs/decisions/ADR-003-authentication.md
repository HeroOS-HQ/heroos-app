# ADR-003 — Authentication and Application Authorization

**Status:** Accepted  
**Date:** 2026-10-08  
**Owner:** Technical Lead  
**Milestone:** M1 — Foundation & Security  
**Issue:** M1-01 — Finalize V1 architecture & security baseline

## Context

HeroOS processes private company, employee and HR case information.

V1 therefore requires a clear separation between:

1. authentication — establishing who the caller is
2. authorization — establishing which HeroOS company/resources the caller may access

HeroOS must not implement or maintain its own password-storage system.

Authentication should use a managed identity service while company membership
and tenant authorization remain part of the HeroOS application domain.

The authentication design must support:

- browser-based users
- secure API authentication
- email verification
- password recovery
- future MFA
- user deactivation
- company membership changes
- tenant isolation
- Development, Staging and Production separation

---

## Decision

HeroOS V1 will use **Amazon Cognito User Pools** for customer/application
authentication.

Cognito answers:

> Who is this caller?

HeroOS PostgreSQL and backend application services answer:

> Which HeroOS company may this caller access?

and:

> What may this caller do inside that company?

Authentication and application authorization remain separate concerns.

---

## Authentication Model

The intended flow is:

```text
User
  |
  v
Next.js
  |
  v
Amazon Cognito
  |
  | authenticated identity
  v
HeroOS API
  |
  | validate identity
  v
HeroOS User
  |
  v
Company Membership
  |
  v
Authorized Tenant Context