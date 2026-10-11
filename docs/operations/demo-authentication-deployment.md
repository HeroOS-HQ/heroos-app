# HeroOS Demo Authentication Deployment (B4)

**Status:** Code ready for a provider-neutral OpenID Provider; nothing provisioned or deployed\
**Owner:** Technical Lead\
**Scope:** Temporary M2–M4 demo: Vercel (web) + Render (API) + Supabase (PostgreSQL), synthetic data only. **No AWS before M4 is complete**; Cognito returns in M5\
**Related:** [Authentication §4.3, §10](../architecture/authentication.md),
[ADR-003 addendum](../decisions/ADR-003-authentication.md),
[Delivery Plan §6](../milestones/delivery-plan.md),
[Tenant Isolation](../architecture/tenant-isolation.md), [Database Credentials](database-credentials.md)

Every step below that creates or changes an account, a cloud resource, a
credential or data needs explicit approval first. Nothing here has been run.

## 1. Decisions

| Decision | Value |
| --- | --- |
| Identity provider | A standards-based **OpenID Provider** (to be selected; e.g. Auth0, Zitadel Cloud, Microsoft Entra External ID). Not AWS |
| API | `HEROOS_ENV=staging`, `HEROOS_AUTH_PROVIDER=oidc`: deployed-environment database guards stay on; production remains Cognito-only |
| Web | `HEROOS_WEB_AUTH_PROVIDER=oidc`: Authorization Code + PKCE (S256), endpoints from OIDC discovery, server-side sealed `HttpOnly` session |
| Tokens | RFC 9068 JWT access tokens for the HeroOS API audience; ID tokens are never accepted by the API |
| Users | Admin-created only (public sign-up disabled): the two synthetic demo users |
| Callback | One stable Vercel **production** domain; previews are not registered |
| Company | `HEROOS_DEMO_COMPANY_ID`; the API's Membership check decides access |
| CORS | Not needed (`HEROOS_CORS_ALLOWED_ORIGINS` unset): the browser never calls the API |

## 2. Provider requirements (checklist for selection)

The provider must support all of these; record the choice in the
[Service Inventory](../privacy/third-party-service-inventory.md) §4 and §9 first.

- OIDC discovery at `<issuer>/.well-known/openid-configuration`, listing
  `code` in `response_types_supported` and `S256` in
  `code_challenge_methods_supported`.
- Hosted login page (HeroOS never handles passwords), public clients with
  PKCE, and disabling public sign-up.
- **JWT access tokens for an API audience** (Auth0: an API with an identifier,
  requested with `audience=`), signed RS256 or ES256, in the **RFC 9068
  profile** (`typ: at+jwt`, `client_id`, `jti`). Disabling
  `HEROOS_OIDC_REQUIRE_RFC9068` is allowed only after the provider's real token
  profile is documented and tested; the client allow-list applies either way.
- RP-Initiated Logout (`end_session_endpoint` on the issuer's origin). Without
  it, sign-out is local only.
- Optional TOTP MFA (confirm whether the free plan includes it).
- Admin account protected with MFA.
- Authorization, token and JWKS endpoints on the issuer's own origin (the web
  app and API refuse others; keys elsewhere need `HEROOS_OIDC_JWKS_URI`).

### Verified profile: Auth0 (intended provider)

Checked on 2026-10-11 against Auth0's documentation ("Access Token Profiles",
"Configure Access Token Profile") and the public metadata of
`https://samples.auth0.com/.well-known/openid-configuration`:

| Requirement | Auth0 |
| --- | --- |
| Issuer | `https://<tenant>.<region>.auth0.com/` (trailing slash, kept verbatim) |
| Endpoints / keys | `/authorize`, `/oauth/token`, `/.well-known/jwks.json` on the issuer origin |
| PKCE / response type | `S256` and `code` listed |
| Access-token profile | API → Access Token Settings → JSON Web Token Profile = **RFC 9068** (Management API `token_dialect: rfc9068_profile`): `typ: at+jwt`, `client_id`, `jti`. The default "Auth0" profile (`typ: JWT`, `azp`, `gty`, no `client_id`/`jti`) is **rejected** by the API |
| Signing | API signing algorithm **RS256** (HS256 is refused by the allow-list) |
| Audience | Request `audience=<API identifier>`; `aud` also contains `<issuer>userinfo` (accepted) |
| Logout | `end_session_endpoint` (`/oidc/logout`) present for tenants created since 14 Nov 2023 or when discovery of it is enabled; otherwise sign-out is local only |

These shapes are pinned in `apps/api/tests/auth/test_oidc_hardening.py` and
`apps/web/src/lib/server/oidc-flow.test.ts`. `HEROOS_OIDC_REQUIRE_RFC9068`
stays `true` for Auth0. Before using any other provider, record its actual
token header and claims and add an equivalent test first.

## 3. Provider configuration (example values)

| Setting | Value |
| --- | --- |
| API / resource | Identifier `https://api.heroos-demo.example` (the audience; must differ from the client ID); signing RS256; RFC 9068 token profile if offered |
| Application | Type single-page/native (**public, no client secret**); grant: authorization code only |
| Allowed callback URL | `https://<vercel-production-domain>/auth/callback` |
| Allowed logout URL | `https://<vercel-production-domain>/` |
| Allowed web origins / CORS | none needed (the token exchange is server-side) |
| Sign-up | Disabled |
| Access-token lifetime | 60 minutes or less |
| Users | `demo-alpha-admin`, `demo-beta-admin`, generated passwords stored only in the private secrets directory (0600) |

Record each user's `sub` (e.g. `auth0|…`); it is assigned by the provider.

## 4. Map the identities to the seeded users (Supabase write)

`users.identity_subject` must equal the provider's `sub`. In one guarded admin
transaction (identity guard as in the Supabase initialization), update exactly
the two seed users and verify before commit:

```sql
UPDATE users SET identity_subject = '<alpha-sub>', updated_at = now()
 WHERE id = 'd3e0a000-0000-4000-8000-000000000101' AND identity_subject = 'synthetic-demo|alpha-admin';
UPDATE users SET identity_subject = '<beta-sub>', updated_at = now()
 WHERE id = 'd3e0b000-0000-4000-8000-000000000101' AND identity_subject = 'synthetic-demo|beta-admin';
-- expect 1 row each; Memberships and tenant data are unchanged
```

Rollback: the same statements with the values swapped back to the
`synthetic-demo|…` placeholders.

## 5. Render (API)

Docker service from `apps/api/Dockerfile` (build context: repository root),
health check `/health`, port 8000. Auto-deploy **off** until approved.

| Variable | Value | Secret |
| --- | --- | --- |
| `HEROOS_ENV` | `staging` | no |
| `HEROOS_AUTH_PROVIDER` | `oidc` | no |
| `HEROOS_OIDC_ISSUER` | the discovery `issuer`, verbatim (e.g. `https://<tenant>.<region>.auth0.com/`) | no |
| `HEROOS_OIDC_AUDIENCE` | the API identifier | no |
| `HEROOS_OIDC_CLIENT_IDS` | the web client ID (**required**) | no |
| `DATABASE_URL` | `postgresql+psycopg://heroos_app.<project-ref>:<password>@<session-pooler-host>:5432/postgres?sslmode=verify-full&sslrootcert=/app/certs/supabase-root-2021-ca.crt` | **yes** |
| `HEROOS_LOG_LEVEL` | `INFO` | no |
| `PORT` | `8000` (the port the image listens on) | no |

No Secret File. The public Supabase Root 2021 CA is committed at
`apps/api/certs/supabase-root-2021-ca.crt` and built into the image at
`/app/certs/supabase-root-2021-ca.crt` (root-owned, mode 0444). The API runs as
uid 1001, and Render Secret Files under `/etc/secrets` are reported to be
readable by root only; an unreadable CA fails every connection closed.

| CA | Value |
| --- | --- |
| Subject | `CN=Supabase Root 2021 CA, O=Supabase Inc` (self-signed root, `CA:TRUE`) |
| SHA-256 | `80:70:25:AD:50:D4:ED:21:9D:2C:9C:7D:29:9C:00:4F:82:4E:B0:0C:F7:F6:5A:FE:F6:07:D0:7B:72:E6:CA:FA` |
| Valid until | 2031-04-26 |

`apps/api/tests/test_database_ca.py` pins the fingerprint and the expiry. If
Supabase rotates its CA, replace the file with the one from the project's
Database Settings (SSL certificate), verify it against the live pooler
(`openssl s_client -starttls postgres -connect <session-pooler-host>:5432
-CAfile <file> -verify_hostname <session-pooler-host>`), and update the test.

Must **not** be set: `MIGRATION_DATABASE_URL`,
`HEROOS_DEV_AUTH_SECRET`, `HEROOS_STORAGE_PROVIDER=local`,
`HEROOS_CORS_ALLOWED_ORIGINS`, `NODE_TLS_REJECT_UNAUTHORIZED` (web). Defaults suffice for `HEROOS_OIDC_ALGORITHMS`
(`RS256,ES256`) and `HEROOS_OIDC_REQUIRE_RFC9068` (`true`).

## 6. Vercel (web)

Project root `apps/web`, Next.js, pnpm workspace install. Variables for the
**Production** environment only (previews get none and show "Sign-in is not configured"):

| Variable | Value | Secret |
| --- | --- | --- |
| `HEROOS_WEB_AUTH_PROVIDER` | `oidc` | no |
| `HEROOS_WEB_ORIGIN` | `https://<vercel-production-domain>` | no |
| `HEROOS_OIDC_ISSUER` | same as the API | no |
| `HEROOS_OIDC_CLIENT_ID` | the web client ID | no |
| `HEROOS_OIDC_AUDIENCE` | same as the API | no |
| `HEROOS_API_BASE_URL` | `https://<render-service>.onrender.com` | no |
| `HEROOS_DEMO_COMPANY_ID` | `d3e0a000-0000-4000-8000-000000000001` (synthetic Company A) | no |
| `HEROOS_WEB_SESSION_SECRET` | `openssl rand -hex 32` | **yes** (Sensitive) |

## 7. Smoke test after deployment

1. `GET https://<render>/health` → 200; `/docs`, `/openapi.json` → 404.
2. `GET https://<render>/companies/<A>/cases` without a token → 401; with an ID
   token from the provider → 401.
3. Web response headers: nonce CSP with `form-action 'self' <issuer origin>`,
   `nosniff`, `DENY`, HSTS.
4. Sign in as `demo-alpha-admin` → Company A and its cases.
5. Sign out → provider logout (or local sign-out), back to the signed-out page.
6. Sign in as `demo-beta-admin` → "Your account does not have access to the demo company."
7. No token in `localStorage`, `sessionStorage` or any non-`HttpOnly` cookie.
8. Tampered session cookie → signed out; `GET /auth/logout` → 405.

## 8. Known limitations

- An access token stays valid until it expires (≤ 60 min) after sign-out
  (stateless API verification); only the web server ever holds it.
- No session renewal; one configured Company.
- If the provider's discovery or JWKS is unreachable, sign-in reports
  "unavailable" and API requests get 401 (fail closed).

## 9. Rollback and teardown

- Before deployment: revert the PR; the Cognito path is untouched.
- After deployment: unset `HEROOS_AUTH_PROVIDER` / `HEROOS_WEB_AUTH_PROVIDER`
  (the API refuses to start in staging; the web reports "not configured"),
  restore the two `identity_subject` placeholders (§4), delete the provider
  tenant, the Render service and the Vercel project, and rotate or drop the
  Supabase `heroos_app` password.

## 10. M5 (Cognito)

At M5 the same code switches to Cognito: `HEROOS_WEB_AUTH_PROVIDER=cognito`
with `HEROOS_COGNITO_DOMAIN` / `HEROOS_COGNITO_CLIENT_ID`, and
`HEROOS_AUTH_PROVIDER=cognito` with `HEROOS_COGNITO_ISSUER` /
`HEROOS_COGNITO_APP_CLIENT_ID` (public App Client, authorization code + PKCE,
`openid`, callback and sign-out URLs as above). Users are re-mapped to Cognito
`sub` values. Provisioning follows the M5 Terraform plan, not this runbook.
