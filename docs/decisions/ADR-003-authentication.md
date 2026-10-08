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
Authorized Tenant Context```

---

## Implementation Decisions (M1-05)

Recorded 2026-10-08 while implementing the foundation. Details:
[Authentication and Company Authorization](../architecture/authentication.md).

1. **Identity mapping.** The Cognito `sub` claim is stored as
   `users.identity_subject` and is the only key used to resolve a HeroOS User.
   Email is never used for identity mapping or authorization. Users are not
   provisioned just-in-time; an unknown identity is denied.
2. **Token type.** The HeroOS API accepts Cognito **access tokens**. It
   validates RS256 signature via the User Pool JWKS, `iss`, `exp`, `iat`,
   `token_use == "access"`, `client_id` equal to the configured App Client, and
   a non-empty `sub`. Tokens carrying `aud` (ID tokens) are rejected.
3. **Company authorization.** Access to a Company requires a `memberships` row
   for the resolved User and the requested Company. A client-supplied Company ID
   only identifies the requested resource.
4. **Failure semantics.** Authentication failures return a generic 401;
   authorization failures (unknown User, missing Membership) return an identical
   generic 403.
5. **Development authentication.** Local development uses a signed HS256 JWT
   provider behind the same provider contract. Settings validation, application
   startup and the provider itself refuse it outside `HEROOS_ENV=development`;
   staging and production require the Cognito provider.
6. **Activation.** Creating the User Pool, the App Client and real Staging
   authentication is deferred to M3.
