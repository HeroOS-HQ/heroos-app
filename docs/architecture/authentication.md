# HeroOS Authentication and Company Authorization

**Status:** Implemented foundation (M1-05); live Cognito activation deferred to M3\
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
| `aud` | Must be absent. Cognito access tokens have no `aud`; a token carrying one (e.g. an ID token) is rejected |
| `sub` | Required, non-empty, at most 255 characters; becomes `VerifiedIdentity.subject` |

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
| `HEROOS_ENV` | all | `development` (default), `staging` or `production` |
| `HEROOS_AUTH_PROVIDER` | all | `development` or `cognito`. Required and must be `cognito` in staging/production. Unset in development rejects every protected request |
| `HEROOS_DEV_AUTH_SECRET` | development only | Startup fails if set in staging/production |
| `HEROOS_COGNITO_ISSUER` | when `cognito` | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>`, https, no trailing `/` |
| `HEROOS_COGNITO_APP_CLIENT_ID` | when `cognito` | App Client ID of the HeroOS web client |
| `HEROOS_COGNITO_JWKS_URI` | optional | Defaults to `<issuer>/.well-known/jwks.json`; must be https |

Secrets use `SecretStr`, and settings validation errors hide input values, so
neither repr nor startup errors print the development secret or `DATABASE_URL`.
Cognito access-token verification needs no client secret.

## 7. Credential Logging

- The API logs only fixed failure reasons (for example `cognito token rejected
  (ExpiredSignatureError)`) and, for 403s, the requested Company ID. It never logs
  the `Authorization` header, raw tokens or token fragments.
- Verification exceptions are re-raised `from None`, so PyJWT messages and
  tracebacks do not travel with the HTTP error.
- Response bodies are fixed strings and never echo the credential.
- The application has no request-header logging middleware. Uvicorn access logs
  record the request line only, not headers.
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
  plain equality on UUID columns, which behaves the same on PostgreSQL.
- Protected-request tests mount a test-only route on a test FastAPI app using the
  real dependencies. Only the provider (a real verifier with local keys) and the
  database session are injected. No production debug endpoint exists.

## 9. Boundaries and Deferred Work

**M1-06 — tenant isolation** consumes `AuthenticatedCompanyContext` to add
service/query Company scoping, PostgreSQL Row Level Security as defense in depth,
and cross-tenant data tests. M1-05 authorizes entry into a Company. It does not
scope queries inside the Company.

**M3 — live Cognito activation** includes:

- creating the Cognito User Pool and App Client (Terraform)
- real issuer, App Client ID and JWKS configuration for Staging and Production
- deployment configuration of the `HEROOS_COGNITO_*` variables
- frontend login, Hosted UI/callback URLs, password reset and MFA flows
- real Staging authentication with end-to-end proof

None of these exist yet. M1-05 has not contacted AWS or created Cognito resources.

**Not in scope:** roles, fine-grained permissions, membership lifecycle states,
user provisioning and onboarding.
