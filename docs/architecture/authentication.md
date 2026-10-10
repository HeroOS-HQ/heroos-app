# HeroOS Authentication and Company Authorization

**Status:** Implemented foundation (M1-05); browser sign-in and first Company endpoints for the temporary demo (B4, section 10); Staging/Production Cognito activation deferred to M5 (cloud activation; [Delivery Plan](../milestones/delivery-plan.md))\
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
| Authorization | HeroOS data: `users.identity_subject` and `memberships` | `403 Forbidden` |

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
users.identity_subject == subject          app/auth/service.py: resolve_user
        |  403 if no User (no just-in-time provisioning)
        v
memberships(user_id, company_id)           app/auth/service.py: authorize_company
        |  (RLS: looked up under a transaction-local candidate
        |   scope that is discarded before returning)
        |  403 if no Membership
        v
AuthenticatedCompanyContext                app/auth/models.py
(user_id, company_id, membership_id, identity_subject)
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
  row for the authenticated User and the requested Company. Under the current
  schema the existence of the Membership is the authorization relationship;
  there are no roles or membership states yet.
- **A client-supplied Company ID is a resource identifier, not evidence.** Path,
  query, header, body and token claims (e.g. `custom:company_id`) never authorize.
  Changing `company_id` re-runs the Membership lookup.
- **`identity_subject` is the stable identity key.** It stores the provider's `sub`.
  Email is never used for identity mapping or authorization.
- **Unknown identities are not provisioned.** A verified identity without a User row
  is denied (403). Onboarding that creates Users and Memberships is separate work.
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

## 5. Development Authentication Safety Boundary

`HEROOS_ENV` is required and has no default. If it is missing, or is not one of
`development`, `staging` or `production` (exact, lowercase), settings validation
fails and the API does not start. A missing value never falls back to
development.

The development provider cannot run outside `HEROOS_ENV=development`. This is
enforced in three independent places:

1. **Settings validation** (`app/core/config.py`). When `HEROOS_ENV` is `staging` or
   `production`, `HEROOS_AUTH_PROVIDER` must be `cognito` and
   `HEROOS_DEV_AUTH_SECRET` must not be set at all. Any other combination raises at
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

make dev-token SUBJECT=<users.identity_subject>
curl -H "Authorization: Bearer <token>" http://localhost:8000/companies/<company-id>/...
```

The subject must already exist as `users.identity_subject` and have a Membership
in the requested Company. The helper never creates Users or Memberships.

## 6. Configuration Contract

| Variable | Environments | Notes |
| --- | --- | --- |
| `HEROOS_ENV` | all | **Required, no default.** `development`, `staging` or `production`. Local development gets it from `.env` (copied from `.env.example`) or Docker Compose |
| `HEROOS_AUTH_PROVIDER` | all | `development` or `cognito`. Required and must be `cognito` in staging/production. Unset in development rejects every protected request |
| `HEROOS_DEV_AUTH_SECRET` | development only | Startup fails if set in staging/production |
| `HEROOS_COGNITO_ISSUER` | when `cognito` | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>`, https, no trailing `/` |
| `HEROOS_COGNITO_APP_CLIENT_ID` | when `cognito` | App Client ID of the HeroOS web client |
| `HEROOS_COGNITO_JWKS_URI` | optional | Defaults to `<issuer>/.well-known/jwks.json`; must be https |
| `HEROOS_COGNITO_RESOURCE_AUDIENCE` | optional | Resource-server identifier. When set, access tokens must carry a matching `aud`. Must not be blank |

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
ahead of M5: frontend login, callback and logout against Cognito managed login,
the server-side browser session (section 10), the first Company endpoints and
the CORS and security-header controls. It uses a separate, disposable demo User
Pool in `eu-west-1` with `HEROOS_ENV=staging`, synthetic data only. Deployment:
[Demo Authentication Deployment](../operations/demo-authentication-deployment.md).

**M5 — live Cognito activation** still includes:

- creating the Staging and Production User Pools and App Clients (Terraform)
- real issuer, App Client ID and JWKS configuration for Staging and Production
- deployment configuration of the `HEROOS_COGNITO_*` variables
- password reset and MFA enrolment flows beyond Cognito managed login; refresh
  tokens and session renewal
- real Staging authentication with end-to-end proof

The demo pool is not reused for M5.

**Not in scope:** roles, fine-grained permissions, membership lifecycle states,
user provisioning and onboarding.

## 10. Browser Access (B4)

### 10.1 API endpoints

`app/api/companies.py` ships the first protected routes. Each depends on
`CompanyDb`, so the full chain in section 2 and tenant isolation apply:

| Route | Success | Failures |
| --- | --- | --- |
| `GET /companies/{company_id}` | `{id, name}` | 401, 403 |
| `GET /companies/{company_id}/cases` | cases of that Company | 401, 403 |
| `GET /companies/{company_id}/cases/{case_id}` | one case | 401, 403, 404 |

403 is identical for another Company and a non-existent one. 404 is identical
for another Company's case ID and an ID that exists nowhere. Malformed IDs return
422 without echoing the input. The routes are read-only and never commit.

### 10.2 Browser session: backend-for-frontend

The Next.js server, not the browser, is the OAuth client (`apps/web/src/lib/server/`):

```text
Browser ──GET /auth/login──▶ Next.js server ──302──▶ Cognito managed login
        ◀──302 /auth/callback?code&state──────────────┘
Browser ──GET /auth/callback──▶ Next.js server ──POST /oauth2/token (code + code_verifier)──▶ Cognito
        ◀──303 / + sealed session cookie──┘
Browser ──GET /──▶ Next.js server ──GET /companies/{id}/… Authorization: Bearer <access token>──▶ API
```

- **Authorization Code + PKCE (S256)** with a public App Client (no client
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
  ends the Cognito managed-login session via `/logout`. A copied access token
  stays valid until it expires because API verification is stateless (see the
  M1 closeout risks).
- **Redirects are fixed**: the callback always returns to the configured web
  origin. Provider and API errors map to fixed messages (`?auth=failed|cancelled|expired`,
  "session expired", "no access", "unavailable"); their text is never rendered.
- **No prerendering of auth routes**: every auth route handler awaits
  `connection()`, so state and verifiers are generated per request (with Cache
  Components a GET handler that reads no request data would be built once).
- **Company choice**: the web app shows one configured Company
  (`HEROOS_DEMO_COMPANY_ID`). That ID is only a resource identifier: the API's
  Membership check decides access, exactly as for any client-supplied ID.

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
