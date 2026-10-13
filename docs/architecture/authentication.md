# HeroOS Authentication and Company Authorization

**Status:** Implemented foundation (M1-05); browser sign-in and first Company endpoints (B4, section 10); provider-neutral OIDC for the pre-M5 demo (section 4.3); Cognito activation deferred to M5 (no AWS before M4 is complete) (cloud activation; [Delivery Plan](../milestones/delivery-plan.md))\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security\
**Issue:** M1-05 — Establish authentication & membership authorization foundation\
**Related:** [ADR-003](../decisions/ADR-003-authentication.md),
[ADR-004](../decisions/ADR-004-data-and-tenancy.md),
[Security Boundaries](security-boundaries.md)

## 1. Summary

Authentication proves **who** is calling. Authorization decides **which Company**
they may act in. They are separate code paths with separate failure modes:

| Concern | Decided by | Failure |
| --- | --- | --- |
| Authentication | An `AuthenticationProvider` verifying the Bearer JWT | `401 Not authenticated` |
| Authorization | HeroOS data: `user_identities`, `users` and `memberships` ([ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md)) | `403 Forbidden` |

A verified token never grants Company access by itself.

## 2. Request Flow

```text
Authorization: Bearer <JWT>
        |
        v
AuthenticationProvider.authenticate()      app/auth/providers/
        |  401 on any failure
        v
VerifiedIdentity(subject, issuer)          app/auth/models.py
        |
        v
user_identities (issuer, subject) exact,  app/auth/service.py: resolve_user
  binding and User both active             (ADR-008; RLS hides inactive rows)
        |  403 if no active binding/User (no just-in-time provisioning)
        v
memberships(user_id, company_id), active  app/auth/service.py: authorize_company
        |  (RLS: looked up under a transaction-local candidate
        |   scope that is discarded before returning)
        |  403 if no active Membership
        v
AuthenticatedCompanyContext                app/auth/models.py
(user_id, company_id, membership_id, identity_id)
```

Protected routes declare a `{company_id}` path parameter and depend on
`CompanyContext` (`app/auth/dependencies.py`):

```python
from app.auth.dependencies import CompanyContext

@router.get("/companies/{company_id}/cases")
def list_cases(context: CompanyContext) -> ...:
    ...  # context.company_id is Membership-authorized
```

`AuthenticatedCompanyContext` exists only after credential verification, User
resolution and a Membership lookup. Its `company_id` is taken from the Membership
row.

`memberships` is protected by PostgreSQL Row-Level Security (M1-06), so the
Membership lookup runs with the requested Company as a transaction-local
*candidate* scope, restricted to the authenticated User, and the scope is
discarded before `authorize_company` returns. Setting the candidate scope is
not authorization: only an existing Membership is. Routes that touch tenant
data then depend on `CompanyDb`, which scopes a new transaction to the trusted
context. See [Tenant Isolation §6](tenant-isolation.md#6-membership-authorization-bootstrap).

## 3. Security Invariants

- **Company is the tenant boundary.** Access is granted only by a `memberships`
  row for the authenticated User and the requested Company. An *active*
  Membership is the authorization relationship. Lifecycle:
  [ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md).
- **The Company role is a Membership fact** (M1-10C,
  [ADR-010](../decisions/ADR-010-company-registration-and-administrators.md)):
  `member` or `company_admin`, read from the same row and carried in
  `AuthenticatedCompanyContext.role`. Token claims (groups, `custom:*`), email,
  Company names and request fields never grant a role. Administrator-only
  routes depend on `CompanyAdminDb`, which re-checks the role inside the write
  transaction.
- **A client-supplied Company ID is a resource identifier, not evidence.** Path,
  query, header, body and token claims (e.g. `custom:company_id`) never authorize.
  Changing `company_id` re-runs the Membership lookup.
- **`users.id` is the stable identity; `(issuer, subject)` is the external key.**
  A verified identity maps to a User only through an exact, active
  `user_identities` binding (issuer and `sub`, never normalized). Email and every
  other claim are never used for identity mapping or authorization. Bindings are
  immutable and unique for all time; changing provider adds a binding, it never
  rewrites one (ADR-008).
- **Unknown identities reach one route only.** A verified identity without an
  active binding is denied (403) everywhere except founder self-registration
  (`POST /company-registrations`, M1-10C), which creates a *new* Company with
  that person as its first administrator through one narrow database function,
  and only when `HEROOS_SELF_REGISTRATION_ENABLED` is set. No route can grant
  access to an existing Company, assign a role or change lifecycle: that stays
  with the audited operator CLI
  ([Identity Provisioning](../operations/identity-provisioning.md),
  [Company Registration](../operations/company-registration.md)).
- **Lifecycle is checked on every request.** A suspended User, revoked binding or
  revoked Membership is denied on the next request, also while an access token is
  still valid, by the application and by Row-Level Security for the API role.
- **Generic failures.** Every authentication failure returns the same 401 body with
  `WWW-Authenticate: Bearer`. Unknown User, missing Membership and non-existent
  Company all return the same 403 body, so callers cannot probe which records
  exist.
- **Fail closed.** Missing, malformed, unsigned, expired or otherwise invalid
  credentials are rejected. If no provider is configured (development only), every
  protected request is rejected.
- **No credentials in logs or errors.** See section 7.

## 4. Providers

Both providers implement `AuthenticationProvider.authenticate(token) ->
VerifiedIdentity` and raise `AuthenticationError` on any failure. Providers do not
read Users or Memberships.

### 4.1 Cognito access tokens (production target)

`app/auth/providers/cognito.py`. HeroOS accepts **Cognito access tokens** for API
calls. ID tokens are intended for the client to learn about the user, not to
authorize API calls; access tokens identify the App Client that obtained them and
carry `token_use=access`.

Validation performed on every request:

| Check | Rule |
| --- | --- |
| Signature | RS256 only, key selected by the header `kid` from the User Pool JWKS |
| `iss` | Equals `HEROOS_COGNITO_ISSUER` exactly |
| `exp` | Required; expired tokens rejected (no leeway) |
| `iat` | Required |
| `token_use` | Must equal `access` |
| `client_id` | Must equal `HEROOS_COGNITO_APP_CLIENT_ID` |
| `aud` | Only checked when `HEROOS_COGNITO_RESOURCE_AUDIENCE` is set: `aud` must then be present and equal (or, for a list, contain) that value. When unset, `aud` is ignored |
| `sub` | Required, non-empty, at most 255 characters; becomes `VerifiedIdentity.subject` |

`token_use` is the only access-vs-ID-token discriminator. The presence of `aud` is
not, because Cognito access tokens can legitimately carry `aud` when resource
binding is used. An ID token (`token_use=id`) is always rejected, whether or not
it carries `aud` or `client_id`. A matching resource audience never relaxes any
other check.

Algorithm confusion (e.g. HS256 signed with the RSA public key) and `alg=none` are
rejected because only RS256 is accepted.

JWKS keys are fetched lazily on first use with PyJWT's `PyJWKClient` (1 hour cache,
5 second timeout, refetch cooldown on unknown `kid`), so application startup never
contacts AWS. A JWKS fetch failure fails closed with 401.

Scope-based authorization (`scope` claim) is not used in V1.

### 4.2 Development provider (local only)

`app/auth/providers/development.py`. A real verifier, not a bypass:

- HS256 JWT signed with `HEROOS_DEV_AUTH_SECRET` (at least 32 characters)
- dedicated issuer `urn:heroos:local-development`
- required `iss`, `sub`, `iat`, `exp`; 15 minute default lifetime, tokens with a
  lifetime over 60 minutes are rejected
- sent as a normal `Authorization: Bearer` header

It authenticates only. A development token for a subject with no User or no
Membership is denied exactly like a Cognito token would be.

Header-based identity shortcuts such as `X-User-ID`, `X-Dev-User` or `X-Company-ID`
do not exist and are ignored.

### 4.3 Provider-neutral OIDC access tokens (staging demo, pre-M5)

`app/auth/providers/oidc.py`. AWS is not used before M4 is complete
([Delivery Plan §6](../milestones/delivery-plan.md)), so the temporary demo
authenticates with a standards-based OpenID Provider instead of Cognito
([ADR-003 addendum](../decisions/ADR-003-authentication.md)). It is allowed in
`development` and `staging` only; **production remains Cognito-only**, checked
in settings validation and again when the provider is built.

| Check | Rule |
| --- | --- |
| Algorithm | Header `alg` must be in `HEROOS_OIDC_ALGORITHMS` (default `RS256,ES256`; asymmetric RS/PS/ES only), checked **before** any key lookup. `none` and HMAC are never accepted |
| Type | RFC 9068 profile (default): header `typ` must be `at+jwt` |
| Keys | JWKS from OIDC discovery (`<issuer>/.well-known/openid-configuration`), whose `issuer` must equal the configured issuer exactly and whose `jwks_uri` must be https **on the issuer's origin**; a provider that serves keys elsewhere needs an explicit `HEROOS_OIDC_JWKS_URI`. Discovery and keys are fetched over https with explicit certificate and host-name verification, **never following redirects**, discovery capped at 256 KiB; unknown `kid` refetches are rate-limited (PyJWT cooldown). Fetched lazily (startup never contacts the provider); failures are not cached and fail closed (401) |
| `iss` | Equals `HEROOS_OIDC_ISSUER` verbatim (a trailing `/` is significant) |
| `aud` | Must contain `HEROOS_OIDC_AUDIENCE`, the HeroOS API identifier |
| `exp`, `iat`, `nbf` | `exp` and `iat` required; expired or not-yet-valid tokens rejected (no leeway) |
| `client_id`, `jti` | Required with the RFC 9068 profile |
| Client | `HEROOS_OIDC_CLIENT_IDS` is **required**. The token's client (`client_id` and/or `azp`; both must agree when present) must be a string in that list, with or without the RFC 9068 profile |
| `sub` | Required, non-empty, at most 255 characters |

**ID tokens are never accepted as access tokens**: an ID token's `aud` is the
client ID, and settings refuse an API audience equal to any client ID; ID tokens
lack `typ: at+jwt`; and tokens carrying ID-token-only claims (`nonce`,
`at_hash`, `c_hash`) are rejected.

## 5. Development Authentication Safety Boundary

`HEROOS_ENV` is required and has no default. If it is missing, or is not one of
`development`, `staging` or `production` (exact, lowercase), settings validation
fails and the API does not start. A missing value never falls back to
development.

The development provider cannot run outside `HEROOS_ENV=development`. This is
enforced in three independent places:

1. **Settings validation** (`app/core/config.py`). When `HEROOS_ENV` is `staging`,
   `HEROOS_AUTH_PROVIDER` must be `cognito` or `oidc`; when it is `production`, it
   must be `cognito`. Outside development `HEROOS_DEV_AUTH_SECRET` must not be set
   at all. Any other combination raises at
   settings load.
2. **Application startup** (`app/main.py`). Settings are loaded and the provider is
   built at import, so a misconfigured API process exits before serving requests.
3. **Provider and token issuance** (`DevelopmentAuthenticationProvider`,
   `issue_development_token`). Both re-check the environment, so they cannot be
   constructed for a deployed environment even if settings validation were
   bypassed.

There is no HTTP endpoint that mints tokens. The local helper below is not copied
into the API container image.

### Local usage

```bash
# .env (copied from .env.example) contains:
#   HEROOS_ENV=development
#   HEROOS_AUTH_PROVIDER=development
#   HEROOS_DEV_AUTH_SECRET=<local value, 32+ characters>

make dev-token SUBJECT=<subject bound under urn:heroos:local-development>
curl -H "Authorization: Bearer <token>" http://localhost:8000/companies/<company-id>/...
```

The subject must already be bound (active) under the development issuer
`urn:heroos:local-development` and have an active Membership in the requested
Company. The helper never creates Users, bindings or Memberships.

## 6. Configuration Contract

| Variable | Environments | Notes |
| --- | --- | --- |
| `HEROOS_ENV` | all | **Required, no default.** `development`, `staging` or `production`. Local development gets it from `.env` (copied from `.env.example`) or Docker Compose |
| `HEROOS_AUTH_PROVIDER` | all | `development`, `cognito` or `oidc`. Required outside development: `cognito` or `oidc` in staging, `cognito` in production. Unset in development rejects every protected request |
| `HEROOS_DEV_AUTH_SECRET` | development only | Startup fails if set in staging/production |
| `HEROOS_COGNITO_ISSUER` | when `cognito` | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>`, https, no trailing `/` |
| `HEROOS_COGNITO_APP_CLIENT_ID` | when `cognito` | App Client ID of the HeroOS web client |
| `HEROOS_COGNITO_JWKS_URI` | optional | Defaults to `<issuer>/.well-known/jwks.json`; must be https |
| `HEROOS_COGNITO_RESOURCE_AUDIENCE` | optional | Resource-server identifier. When set, access tokens must carry a matching `aud`. Must not be blank |
| `HEROOS_OIDC_ISSUER` | when `oidc` | Issuer identifier, https, no query or fragment; compared verbatim |
| `HEROOS_OIDC_AUDIENCE` | when `oidc` | HeroOS API identifier required in `aud`; must differ from every client ID |
| `HEROOS_OIDC_CLIENT_IDS` | when `oidc` | **Required.** Comma-separated client IDs allowed to obtain tokens (`client_id`/`azp`) |
| `HEROOS_OIDC_JWKS_URI` | optional | Overrides discovery (needed only when keys are not on the issuer's origin); must be https |
| `HEROOS_OIDC_ALGORITHMS` | optional | Default `RS256,ES256`; asymmetric algorithms only |
| `HEROOS_OIDC_REQUIRE_RFC9068` | optional | Default `true` (`typ: at+jwt`, `client_id`, `jti` required) |
| `HEROOS_SELF_REGISTRATION_ENABLED` | optional | Default `false` in every environment. Enables `POST /company-registrations` (404 otherwise). An activation step, together with the identity provider's sign-up setting ([Company Registration §3](../operations/company-registration.md#3-activating-founder-self-registration-separate-approval)) |

Secrets use `SecretStr`, and settings validation errors hide input values, so
neither repr nor startup errors print the development secret or `DATABASE_URL`.
Cognito access-token verification needs no client secret.

Database configuration is separate. `DatabaseSettings`
(`app/core/database_settings.py`) holds only `DATABASE_URL` (the API's
RLS-restricted runtime role) and `MIGRATION_DATABASE_URL` (the migration/admin
role), and the API `Settings` extends it with environment and authentication.
Alembic (`migrations/env.py`) loads `DatabaseSettings`, connects with
`MIGRATION_DATABASE_URL` and never imports the API settings module, so
migration jobs need no `HEROOS_ENV` or Cognito configuration. See
[Tenant Isolation §5](tenant-isolation.md#5-database-roles).

## 7. Credential Logging

- The API logs only fixed failure reasons (for example `cognito token rejected
  (ExpiredSignatureError)`) and, for 403s, the requested Company ID. It never logs
  the `Authorization` header, raw tokens or token fragments.
- Verification exceptions are re-raised `from None`, so PyJWT messages and
  tracebacks do not travel with the HTTP error.
- Response bodies are fixed strings and never echo the credential.
- The application has no request-header logging middleware. Since M1-07 the
  Uvicorn access log (which recorded the raw request line, including the query
  string) is disabled. The structured `request_completed` event logs only the
  route template ([Observability](observability.md)).
- `test_bearer_tokens_not_logged_or_echoed` captures all log output at DEBUG across
  valid, invalid and denied requests and asserts no token or signature segment
  appears in logs or responses.

Future logging or observability middleware must preserve this: never record
`Authorization` headers or cookies.

## 8. Testing

`apps/api/tests/auth/` runs in `make check` with no AWS, network or PostgreSQL:

- RSA keys and the JWKS are generated in-process; the production `PyJWKClient`
  key-selection code runs against that local JWKS.
- Users, Companies and Memberships use the real SQLAlchemy models and queries on
  in-memory SQLite, so the Membership query itself is exercised. The lookup is
  plain equality on UUID columns, which behaves the same on PostgreSQL. SQLite
  has no RLS, so the PostgreSQL tenant-context calls are inert stand-ins there.
- The same semantics (401, identical 403s, member allowed) are re-proven on
  real PostgreSQL with RLS and the runtime role by `make tenant-isolation-check`
  (`tests/tenant_isolation/test_http_isolation.py`,
  `test_membership_bootstrap.py`).
- Protected-request tests mount a test-only route on a test FastAPI app using the
  real dependencies. Only the provider (a real verifier with local keys) and the
  database session are injected. No production debug endpoint exists.

## 9. Boundaries and Deferred Work

**M1-06 — tenant isolation** (implemented) consumes
`AuthenticatedCompanyContext` for Company-scoped repositories, a
transaction-local PostgreSQL tenant context and Row-Level Security. M1-05
authorizes entry into a Company. M1-06 scopes every query inside it. See
[Tenant Isolation](tenant-isolation.md).

**B4 — temporary demo (Vercel + Render + Supabase)** implements the browser side
ahead of M5: frontend login, callback and logout, the server-side browser
session (section 10), the first Company endpoints and the CORS and
security-header controls. Because AWS is not used before M4 is complete, the
demo signs in with a provider-neutral OpenID Provider (section 4.3) under
`HEROOS_ENV=staging`, synthetic data only. Deployment:
[Demo Authentication Deployment](../operations/demo-authentication-deployment.md).

**M5 — live Cognito activation** still includes:

- creating the Staging and Production User Pools and App Clients (Terraform)
- real issuer, App Client ID and JWKS configuration for Staging and Production
- deployment configuration of the `HEROOS_COGNITO_*` variables
- password reset and MFA enrolment flows beyond Cognito managed login; refresh
  tokens and session renewal
- real Staging authentication with end-to-end proof

At M5 the web app switches to `HEROOS_WEB_AUTH_PROVIDER=cognito` and the API to
`HEROOS_AUTH_PROVIDER=cognito`. Users keep their `users.id`: each gets an
additional Cognito binding, then the old binding is revoked (ADR-008 §Cognito).

**M1-10B — identity and provisioning** (implemented): issuer-qualified bindings,
User/binding/Membership lifecycle, operator-only provisioning and trigger-written
security audit. See [ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md).

**M1-10C — Company registration and administrators** (implemented): founder
self-registration, `company_admin`/`member` roles, Company Blueprint licensing
and jurisdiction readiness. See
[ADR-010](../decisions/ADR-010-company-registration-and-administrators.md).

**Not in scope:** invitations and fine-grained permissions (later milestones),
the onboarding and Company selection UI (M1-10D).

## 10. Browser Access (B4)

### 10.1 API endpoints

`app/api/companies.py` ships the first protected routes. Each depends on
`CompanyDb`, so the full chain in section 2 and tenant isolation apply:

| Route | Success | Failures |
| --- | --- | --- |
| `GET /companies/{company_id}` | `{id, name}` | 401, 403 |
| `GET /companies/{company_id}/membership` | the caller's role in that Company (M1-10C) | 401, 403 |
| `GET /companies/{company_id}/blueprint` | Blueprint and jurisdiction readiness (M1-10C) | 401, 403 |
| `PATCH /companies/{company_id}/blueprint` | administrators only (M1-10C) | 401, 403, 422 |
| `GET /companies/{company_id}/cases` | cases of that Company | 401, 403 |
| `GET /companies/{company_id}/cases/{case_id}` | one case | 401, 403, 404 |
| `POST /company-registrations` | founder self-registration (M1-10C); any verified identity | 401, 403, 404 (disabled), 422 |
| `GET /me/companies` | the caller's own active Memberships (M1-10C) | 401, 403 |

403 is identical for another Company and a non-existent one. 404 is identical
for another Company's case ID and an ID that exists nowhere. Malformed IDs return
422 without echoing the input. Only the Blueprint update and founder
registration commit. Contract details for M1-10D:
[Company Registration §6](../operations/company-registration.md#6-m1-10d-integration-contract).

### 10.2 Browser session: backend-for-frontend

The Next.js server, not the browser, is the OAuth client (`apps/web/src/lib/server/`):

```text
Browser ──GET /auth/login──▶ Next.js server ──302──▶ Cognito managed login
        ◀──302 /auth/callback?code&state──────────────┘
Browser ──GET /auth/callback──▶ Next.js server ──POST /oauth2/token (code + code_verifier)──▶ Cognito
        ◀──303 / + sealed session cookie──┘
Browser ──GET /──▶ Next.js server ──GET /companies/{id}/… Authorization: Bearer <access token>──▶ API
```

- **Provider**: `HEROOS_WEB_AUTH_PROVIDER=cognito` (fixed managed-login
  endpoints) or `oidc` (endpoints from OIDC discovery, accepted only when the
  document's `issuer` matches exactly, the authorization and token endpoints
  are https on the issuer's origin, and `code` and PKCE `S256` are supported;
  fetched without following redirects; cached for an hour, failures not cached). For `oidc` the
  authorize request adds `audience=<API identifier>` so the access token is a
  JWT for the HeroOS API.
- **Authorization Code + PKCE (S256)** with a public client (no client
  secret). `state` and the PKCE verifier live in a sealed, 10-minute,
  single-use login cookie; the callback compares `state` in constant time and
  never contacts Cognito when it does not match.
- **Only the access token is kept**, in the session cookie. ID and refresh
  tokens from the token response are discarded, so a session ends when the
  access token expires (at most 60 minutes); the user signs in again.
- **Cookies** are `__Host-` prefixed, `HttpOnly`, `Secure`, `SameSite=Lax`,
  `Path=/`, and sealed with AES-256-GCM using a per-purpose HKDF key and the
  purpose as additional data, so a login cookie cannot be used as a session and
  tampering is rejected. Key: `HEROOS_WEB_SESSION_SECRET` (web server only).
- **The browser never holds a token** and never calls the API: the web server
  attaches the bearer token server-side. No browser JavaScript can read or
  exfiltrate it, and the API needs no CORS for the web app.
- **Logout** is `POST /auth/logout` only, accepted only when `Origin` (or
  `Sec-Fetch-Site`) proves a same-origin request; it clears both cookies and
  ends the provider session: Cognito `/logout`, or OIDC RP-Initiated Logout
  (`client_id` + `post_logout_redirect_uri`) when the discovered
  `end_session_endpoint` is on the issuer's origin (the only origin CSP
  `form-action` allows); otherwise sign-out is local only. A copied access token
  stays valid until it expires because API verification is stateless (see the
  M1 closeout risks).
- **Redirects are fixed**: the callback always returns to the configured web
  origin. Provider and API errors map to fixed messages (`?auth=failed|cancelled|expired`,
  "session expired", "no access", "unavailable"); their text is never rendered.
- **No prerendering of auth routes**: every auth route handler awaits
  `connection()`, so state and verifiers are generated per request (with Cache
  Components a GET handler that reads no request data would be built once).
- **Sign-up entry** (M1-10D): `GET /auth/signup` is the same flow with a
  fixed `screen_hint=signup` (OIDC only; Auth0 opens its sign-up form, other
  providers ignore the parameter). It lands on `/onboarding` after the callback.
  The landing path travels in the sealed login cookie, never in the URL.
  Whether sign-up is possible is the provider's setting.
- **Company choice** (M1-10D): `GET /me/companies` lists the user's
  workspaces. `HEROOS_DEMO_COMPANY_IDS` (or the legacy single
  `HEROOS_DEMO_COMPANY_ID`) is now optional. It is used only when the API has no
  `/me/companies` (answers 404, an API older than M1-10C), and the API still
  authorizes each candidate. The IDs are only resource identifiers in either
  case: the API's identity-binding and Membership checks decide access.
- **Mutations** (M1-10D): `POST /bff/registrations` and
  `PATCH /bff/companies/{id}/blueprint` are Route Handlers on the web server.
  - They accept only same-origin requests. The check is the same as logout's:
    `Origin`, or `Sec-Fetch-Site` when the browser sends `Origin: null` under
    `no-referrer`.
  - They also require JSON within 16 KiB and a session.
  - The body is parsed strictly and rebuilt before the API is called with the
    session's token.
  - Responses are fixed codes, `no-store`.

  Server Actions are not used because their origin check rejects
  `Origin: null`. Details:
  [Customer Onboarding and Workspace UI §7](web-onboarding.md#7-security).

Why not tokens in the browser: HeroOS handles HR data, and a script injection
could read tokens kept in `localStorage`/`sessionStorage`. The session design
keeps tokens out of reach of page JavaScript.

### 10.3 CORS and security headers

- **CORS** (`app/core/http_security.py`): disabled unless
  `HEROOS_CORS_ALLOWED_ORIGINS` lists exact origins. Wildcards, paths,
  credentials, uppercase and plain `http` (except localhost in development) are
  rejected at startup. Allowed: `GET` only, `Authorization` only, no
  credentials. The demo leaves it unset.
- **API headers** on every response: `X-Content-Type-Options: nosniff`,
  `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`; outside development also a deny-all CSP and HSTS.
  Interactive docs and `/openapi.json` are published only in development.
- **Web headers**: a per-request nonce CSP from `apps/web/src/proxy.ts`
  (`script-src 'self' 'nonce-…' 'strict-dynamic'`, no `unsafe-inline`,
  `frame-ancestors 'none'`, `form-action 'self' <Cognito origin>`), plus static
  `nosniff`, `no-referrer`, `DENY`, `Cross-Origin-Opener-Policy`,
  `Permissions-Policy` and HSTS from `next.config.ts`. Nonces are incompatible
  with a prerendered static shell, so the root layout renders per request
  (`instant = false`).
- **Caching of signed-in pages**:
  - Self-hosted, Next.js marks dynamic pages
    `private, no-cache, no-store, max-age=0, must-revalidate`.
  - The live Vercel deployment serves them as
    `public, max-age=0, must-revalidate`, with Vercel's CDN holding only the
    prerendered shell. The HTML is still rendered per request: each response
    has a fresh CSP nonce.
  - Because `no-store` is missing there, signed-in pages carry
    `BackForwardCacheGuard` (M1-10E). A page never comes back from the browser's
    back/forward cache after sign-out; it reloads instead.
