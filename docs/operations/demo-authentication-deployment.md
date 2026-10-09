# HeroOS Demo Authentication Deployment (B4)

**Status:** Code ready (branch `feature/b4-cognito-demo-auth`); nothing provisioned or deployed\
**Owner:** Technical Lead\
**Scope:** Temporary M2–M4 demo: Vercel (web) + Render (API) + Supabase (PostgreSQL), synthetic data only. Replaced by AWS in M5\
**Related:** [Authentication §10](../architecture/authentication.md#10-browser-access-b4),
[Tenant Isolation](../architecture/tenant-isolation.md), [Database Credentials](database-credentials.md)

Every step below that creates or changes a cloud resource, a credential or data
needs explicit approval first. Commands are shown for review; none has been run.

## 1. Decisions

| Decision | Value |
| --- | --- |
| Identity provider | Amazon Cognito, a **separate demo User Pool** in `eu-west-1`; not reused for M5 |
| API environment | `HEROOS_ENV=staging`: Cognito required, local DB hosts, the migration credential and the dev provider refused |
| Flow | Authorization Code + PKCE (S256), public App Client, Cognito managed login |
| Users | Admin-created only (self sign-up disabled); the two synthetic demo users |
| MFA | Optional TOTP (authenticator app); no SMS |
| Callback domain | One stable Vercel **production** domain; previews are not registered |
| Company | `HEROOS_DEMO_COMPANY_ID` configured in the web app; the API's Membership check decides access |
| Browser session | Server-side (backend-for-frontend): sealed `HttpOnly` cookie, the browser never holds a token |
| CORS | Not needed (`HEROOS_CORS_ALLOWED_ORIGINS` unset): the browser never calls the API |

## 2. Cognito demo User Pool (eu-west-1)

| Setting | Value |
| --- | --- |
| Pool name | `heroos-demo-users` |
| Sign-in identifier | Username |
| Self-registration | **Disabled** (admin creates users) |
| MFA | Optional; software token (TOTP) only |
| Password policy | At least 14 characters, upper, lower, number, symbol; temporary password validity 1 day |
| Account recovery | None needed (admin-set passwords; demo users have no real mailbox) |
| User existence errors | Prevented (`PreventUserExistenceErrors=ENABLED`) |
| Managed login domain | Cognito prefix domain, e.g. `heroos-demo-<random>` → `https://heroos-demo-<random>.auth.eu-west-1.amazoncognito.com` |

App Client (`heroos-demo-web`):

| Setting | Value |
| --- | --- |
| Client type | **Public, no client secret** (`GenerateSecret=false`) |
| OAuth grant | **Authorization code only** (no implicit, no client credentials) |
| Scopes | `openid` |
| Allowed callback URL | `https://<vercel-production-domain>/auth/callback` (exactly one) |
| Allowed sign-out URL | `https://<vercel-production-domain>/` |
| Identity provider | Cognito user pool only |
| Explicit auth flows | `ALLOW_REFRESH_TOKEN_AUTH` only (required by Cognito; the web app discards refresh tokens) |
| Token validity | Access 60 min, ID 60 min, refresh 60 min |
| Token revocation | Enabled |

API verification needs only the issuer and App Client ID; there is no client
secret anywhere.

Illustrative AWS CLI (placeholders; review before any run):

```bash
aws cognito-idp create-user-pool --region eu-west-1 --pool-name heroos-demo-users \
  --admin-create-user-config AllowAdminCreateUserOnly=true \
  --mfa-configuration OPTIONAL \
  --policies 'PasswordPolicy={MinimumLength=14,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true,TemporaryPasswordValidityDays=1}' \
  --user-pool-tags Project=HeroOS,Environment=demo,ManagedBy=manual
aws cognito-idp set-user-pool-mfa-config --region eu-west-1 --user-pool-id <pool-id> \
  --software-token-mfa-configuration Enabled=true --mfa-configuration OPTIONAL
aws cognito-idp create-user-pool-domain --region eu-west-1 --user-pool-id <pool-id> --domain heroos-demo-<random>
aws cognito-idp create-user-pool-client --region eu-west-1 --user-pool-id <pool-id> \
  --client-name heroos-demo-web --no-generate-secret \
  --allowed-o-auth-flows code --allowed-o-auth-scopes openid --allowed-o-auth-flows-user-pool-client \
  --callback-urls https://<vercel-production-domain>/auth/callback \
  --logout-urls https://<vercel-production-domain>/ \
  --supported-identity-providers COGNITO \
  --explicit-auth-flows ALLOW_REFRESH_TOKEN_AUTH \
  --prevent-user-existence-errors ENABLED --enable-token-revocation \
  --access-token-validity 60 --id-token-validity 60 --refresh-token-validity 60 \
  --token-validity-units AccessToken=minutes,IdToken=minutes,RefreshToken=minutes
```

### Demo users

Create `demo-alpha-admin` and `demo-beta-admin` with `admin-create-user
--message-action SUPPRESS`, then set generated permanent passwords with
`admin-set-user-password --permanent`. Store the passwords only in the private
secrets directory (0600), never in the repository, tickets or chat. Record each
user's `sub` (`admin-get-user` → `sub` attribute); `sub` is assigned by Cognito
and cannot be chosen.

## 3. Map the Cognito identities to the seeded users (Supabase write)

`users.identity_subject` must equal the Cognito `sub`
([Authentication §3](../architecture/authentication.md#3-security-invariants)).
The synthetic seed currently uses placeholder subjects. In one guarded admin
transaction (identity guard as in the Supabase initialization), update exactly
the two seed users and verify before commit:

```sql
UPDATE users SET identity_subject = '<alpha-sub>', updated_at = now()
 WHERE id = 'd3e0a000-0000-4000-8000-000000000101' AND identity_subject = 'synthetic-demo|alpha-admin';
UPDATE users SET identity_subject = '<beta-sub>', updated_at = now()
 WHERE id = 'd3e0b000-0000-4000-8000-000000000101' AND identity_subject = 'synthetic-demo|beta-admin';
-- expect 1 row each; Memberships and tenant data are unchanged
```

## 4. Render (API)

Docker service from `apps/api/Dockerfile` (build context: repository root).
Health check path `/health`. The container listens on port 8000 (set `PORT=8000`
if Render does not detect it).

| Variable | Value | Secret |
| --- | --- | --- |
| `HEROOS_ENV` | `staging` | no |
| `HEROOS_AUTH_PROVIDER` | `cognito` | no |
| `HEROOS_COGNITO_ISSUER` | `https://cognito-idp.eu-west-1.amazonaws.com/<pool-id>` (no trailing `/`) | no |
| `HEROOS_COGNITO_APP_CLIENT_ID` | `<app-client-id>` | no |
| `DATABASE_URL` | `postgresql+psycopg://heroos_app.<project-ref>:<password>@<session-pooler-host>:5432/postgres?sslmode=verify-full&sslrootcert=/etc/secrets/supabase-ca.crt` | **yes** |
| `HEROOS_LOG_LEVEL` | `INFO` | no |

Secret File: `supabase-ca.crt` (the Supabase CA certificate).

Must **not** be set: `MIGRATION_DATABASE_URL`, `HEROOS_DEV_AUTH_SECRET`,
`HEROOS_STORAGE_PROVIDER=local`, `HEROOS_CORS_ALLOWED_ORIGINS`. The API refuses
to start with the first three outside development and with a privileged
database role.

## 5. Vercel (web)

Project root `apps/web`, framework Next.js, pnpm workspace install. Set the
variables for the **Production** environment only; Preview deployments get none
and show "Sign-in is not configured" (their URLs are not registered callbacks).

| Variable | Value | Secret |
| --- | --- | --- |
| `HEROOS_WEB_ORIGIN` | `https://<vercel-production-domain>` | no |
| `HEROOS_COGNITO_DOMAIN` | `https://heroos-demo-<random>.auth.eu-west-1.amazoncognito.com` | no |
| `HEROOS_COGNITO_CLIENT_ID` | `<app-client-id>` | no |
| `HEROOS_API_BASE_URL` | `https://<render-service>.onrender.com` | no |
| `HEROOS_DEMO_COMPANY_ID` | `d3e0a000-0000-4000-8000-000000000001` (synthetic Company A) | no |
| `HEROOS_WEB_SESSION_SECRET` | `openssl rand -hex 32` | **yes** (Sensitive) |

## 6. Smoke test after deployment

1. `GET https://<render>/health` → 200; `/docs` and `/openapi.json` → 404.
2. `GET https://<render>/companies/<A>/cases` without a token → 401.
3. Web: response headers carry the nonce CSP, `nosniff`, `DENY`, HSTS.
4. Sign in as `demo-alpha-admin` → Company A and its cases are shown.
5. Sign out → Cognito logout, back to the signed-out page; reload stays signed out.
6. Sign in as `demo-beta-admin` → "Your account does not have access to the demo company." (403 from the API).
7. Browser storage and DevTools: no token in `localStorage`, `sessionStorage` or
   any non-`HttpOnly` cookie; the session cookie is `__Host-`, `Secure`, `HttpOnly`.
8. Tampered session cookie → signed out; `GET /auth/logout` → 405.

## 7. Known limitations

- An access token is valid until it expires (≤ 60 min) even after sign-out,
  because the API verifies JWTs statelessly. Only the web server ever holds it.
- No session renewal: users sign in again after expiry.
- One configured Company; Company discovery for multi-company users is M2 work.
- Supabase Data API stays disabled; HeroOS tables have no API-role grants.

## 8. Teardown

Delete the demo User Pool (and its domain), the Render service and the Vercel
project; rotate or drop the Supabase `heroos_app` password; remove the demo
secrets directory. None of these carry over to M5.
