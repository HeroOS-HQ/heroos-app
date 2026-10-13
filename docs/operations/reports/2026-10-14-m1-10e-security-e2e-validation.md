# M1-10E: Security, Tenant Isolation and End-to-End Onboarding: Local Validation Report (2026-10-14)

**Branch:** `feature/m1-10e-security-e2e-onboarding`, based on `main` `db03f83` (M1-10D merged)\
**Environment:** local and disposable only. A PostgreSQL 16 container on tmpfs; the real web, API and operator CLI; a local OpenID Provider; headless Chrome.\
**Shared resources:** none touched. Read-only, unauthenticated `GET`s of the public live demo endpoints were made for the inventory (§9).\
**Secrets:** this report contains none: no credentials, tokens, subjects or database URLs.

Status key:
- **Verified locally:** run and passed here.
- **Not run:** stated with the reason.
- **Awaiting approval:** needs the staging deployment ([runbook](../staging-activation.md)).

## 1. Summary

The founder onboarding built in M1-10B, M1-10C and M1-10D was run end to end
with its real components together. It held up: authentication, tenant
isolation, administrator enforcement, revocation, jurisdiction safety and the
whole staged migration behaved as designed.

Five defects were found, reproduced, fixed and covered by regression tests
(§3). None of them granted access to another tenant's data. The most
consequential is a **shared-device privacy defect**:
- on the live Vercel deployment, Back after sign-out could show the previous
  user's workspace;
- the cause is caching headers the platform sends, which differ from
  self-hosted Next.js.

Nothing has been validated against the real staging services yet. That needs
the approvals in §10.

## 2. What ran

| Layer | Command | Result |
| --- | --- | --- |
| Integrated end-to-end (new) | `make e2e-check` | **346** passed, **0** failed, **2** not run (of **348** checks: the screen-reader pass and the backend 422/5xx mapping, see §7–§8); results in `e2e/.output/` |
| Web | `pnpm --filter @heroos/web lint / typecheck / test / build` | Lint and typecheck clean; **425** tests passed; build succeeded |
| API | `uv run ruff check . / ruff format --check . / mypy app scripts / pytest` | Clean; **764** passed, 428 skipped (the database suites, run below) |
| Migrations | `make migration-check` (disposable Compose project) | Passed |
| Tenant isolation | `make tenant-isolation-check` (disposable Compose project) | **391** passed, 3 skipped (Supabase-only role tests, also skipped in CI) |
| Backup and restore | `make backup-restore-check` (disposable Compose project) | **34** passed |
| Privacy register | `make privacy-decision-check` | Passed (22 decisions) |
| Containers | `docker build` of the web and API images (as CI does) | Both built |

End-to-end by suite: api-auth 27, registration 59, isolation 47,
jurisdiction 16, bff 47 (+1 not run), browser 116 (+1 not run), migration 29,
setup and logs 5. The browser suite saved 28 screenshots.

The three database gates ran on a throwaway Compose project (own name and port,
tmpfs, no volume, an empty env file instead of the root `.env`) instead of the
default `heroos-local` project ([recipe](../local-end-to-end-validation.md#5-the-other-database-gates-without-touching-heroos-local)).

**Protected data.** `heroos-local_heroos_postgres_data` was fingerprinted before
and after every run (creation time, mountpoint, labels, attached containers):
unchanged, never attached, never mounted.

## 3. Security audit findings

Severity is about impact on HeroOS and its customers. "Substantiated" means
reproduced or directly observed, not inferred.

| # | Severity | Finding | Evidence | Status |
| --- | --- | --- | --- | --- |
| F1 | **Medium** (privacy, shared devices) | On the live Vercel deployment, signed-in pages are served with `Cache-Control: public, max-age=0, must-revalidate`, not Next.js' self-hosted `private, no-cache, no-store, …`. Without `no-store`, Chrome's back/forward cache restored a signed-in workspace after sign-out: pressing Back showed the previous user's Company | Live headers (read-only); local reproduction with the same header (UI-27v failed before the fix). Each live response carries a fresh CSP nonce, so the CDN does not serve one user's HTML to another | **Fixed**: `BackForwardCacheGuard` on every signed-in page (hide on entering the cache, reload if restored). UI-27 and UI-27v pass, plus unit tests. **Staging re-check ST-19** |
| F2 | **Low** (integrity of an authorization claim) | `POST /company-registrations` answered `role: "company_admin"` for an earlier registration even after an operator had demoted the founder. No privilege followed: every write re-checks the role | R8-10 failed (`answer role company_admin, actual member`); the new PostgreSQL test fails on the old code | **Fixed** in `app.companies.registration` (role read from the active registered Membership) and the web parser. Tests: `test_a_demoted_founder_retrying_registration_is_told_the_role_actually_held`, R8-10, UI-14b |
| F3 | **Low** (UI, CSP) | React streamed the setup-checklist icon's path into a hidden `<svg style="display:none">` container. The nonce CSP blocked the style, logging a violation; in 1 of 30 loads the container was painted for a frame as a 1440×150 px empty box | 30 of 30 workspace-home loads had a blocked style (CSP-R1). No hydration error, no exception, no data exposure (the container held the user's own icon) | **Fixed** without relaxing the CSP: `icons.tsx` is a client module, so icon markup is never split. Then 0 of 100 loads across workspace, settings, ready and homepage (CSP-R1–R3) |
| F4 | **Medium** (operational: staging safety) | The identity runbook said `uv run alembic upgrade head` for B1b. Since M1-10C, `head` is C1, so following it would apply C1 in the same step, without its approval. It also said "deploy the new API", but the API on `main` refuses to start before C1 | Runbook text; the rehearsal (MIG-8, MIG-12) | **Fixed** in the docs: B1b and C1 by revision; the M1-10B API named as `169261d` |
| F5 | **Low** (developer safety) | `make migration-check`, `tenant-isolation-check` and `backup-restore-check` default to the `heroos-local` Compose project, so they create and drop test databases and roles in the local development cluster | Script review | **Documented** with a safe recipe (scripts unchanged) |
| F6 | Info | The live web is already M1-10D, auto-deployed on merge, while the live API predates M1-10C. Signed-in discovery therefore depends on `HEROOS_DEMO_COMPANY_IDS` still being set on Vercel. Without it, users see "We can't reach HeroOS right now" | Deployment records; `/me/companies` → 404 on the live API | Runbook gate S10 (unverified) |
| F7 | Info | Auth0 sign-up appeared enabled on 2026-10-12, so anyone can create an account and reach the neutral welcome. Registration is impossible on the live API (no route), so nothing can be created | Earlier observation; live behaviour | Runbook gate S12 |
| F8 | Info (JJ) | HeroOS never checks `email` or `email_verified`. If verified e-mail must come before registration, Auth0 has to enforce it | Code review; R5-6 (same e-mail claim, separate Users) | Runbook E |
| F9 | Info (JJ) | Reverting a licensing answer to exactly the confirmed one makes the earlier confirmation current again | J-8 | Decision for JJ |
| F10 | Info (design, verified) | RLS keys tenant rows to the transaction's tenant context: with a candidate context the runtime role sees that Company's rows. Authorization is the Membership check, never the context. The runtime role cannot write Companies, Memberships, roles, Users, bindings or confirmations, nor read registrations or audit tables | RLS-1–RLS-6, D-3–D-9 | As designed |

Checked and found sound:
- token validation;
- session cookies;
- the BFF guards;
- login CSRF, PKCE and code replay;
- logout;
- logs (no tokens, cookies or subjects);
- concurrency and idempotency;
- lifecycle denials without sign-out;
- jurisdiction readiness;
- the schema contracts;
- downgrade guards;
- restore fidelity (§5–§8).

## 4. Local integration architecture

[Local End-to-End Validation](../local-end-to-end-validation.md) describes it
in full:
- the Next.js standalone production build behind TLS;
- the FastAPI app under Uvicorn with `HEROOS_ENV=staging` and the production
  OIDC verifier;
- PostgreSQL 16 with every migration, connected as an RLS-restricted runtime
  login;
- the real operator CLI;
- a strict local OpenID Provider (hosted login page, PKCE S256, RFC 9068 tokens,
  RP-initiated logout);
- Chrome over the DevTools protocol.

No application code has a test mode. Only the provider and the hosting
platform's caching header (for UI-27v) are simulated.

## 5. Tenant isolation, authorization and lifecycle

All verified locally against the real API and database:

- **Discovery and cross-tenant access** (D-1–D-9).
  - Two founders each discover only their own Company.
  - Every cross-tenant read and write is 403 with a fixed body, identical for a
    non-existent Company.
  - Another tenant's case id is 404, identical to an unknown id.
  - Malformed ids are 422 and never echoed.
- **Browser** (UI-18–UI-22).
  - Another Company's workspace, settings and ready URLs show "no access", and
    no other-tenant data is present in the HTML.
  - Switching companies leaves no state behind.
  - A member's hand-crafted PATCH is refused.
- **Runtime role** (RLS-1–RLS-6). It sees nothing without a tenant context, and
  only that tenant's rows with one. The context never outlives its transaction
  on the same connection, and every privileged write or read is refused.
- **Roles** (D-10–D-19, UI-23–UI-25).
  - A member can read but not PATCH.
  - An administrator may PATCH only the permitted fields; role, Membership,
    confirmation, readiness and name are refused (422), and nothing is written.
  - Promotion and demotion through the operator take effect at once with the
    same token, and are audited.
  - A settings form left open after demotion cannot save.
- **Revocation and suspension** (D-20, R8-1–R8-9, UI-16–UI-17, UI-25). They
  take effect without sign-out: discovery, reads, writes and re-registration
  are all denied.

## 6. Database migration and recovery

The staging transition was rehearsed on a disposable copy, in the runbook
order (MIG-1–MIG-29). The API generations each step expects ran as real
processes, exported with `git archive`:

| Step | Result |
| --- | --- |
| Pre-M1-10B API `371dd50` on the demo schema | Serves the demo; cross-tenant 403 |
| B1a | Refuses a wrong user count or a missing issuer, leaving nothing changed. Binds every User under the exact issuer (contract 1). The old API keeps working; the current API refuses to start |
| M1-10B API `169261d` | Starts on B1a and authorizes through the bindings |
| B1b | Contract 2. `169261d` keeps working. The pre-M1-10B API now answers 500 (fails closed) |
| C1 | Contract 3. Companies, Users, Memberships and cases preserved. Every Membership became `member` (no promotion). Existing Blueprint data kept; a Company without a Blueprint got an empty one. The legacy `primary_jurisdiction = 'DIFC'` was **not** turned into a confirmation. `169261d` keeps working |
| Current API | Discovery shows the demo user as member. PATCH 403 until an operator appoints the administrator (audited), then 200. Cross-tenant 403 |
| Downgrade | C1 → B1b refused once a role change exists (roll forward only) |
| Backup/restore of C1 | Restores in one transaction. RLS flags, policies, SECURITY DEFINER functions and their ACLs, triggers, table and column grants, audit rows, revision and contract are all identical. **A revocation made after the backup comes back as active access on the restored copy**, which demonstrates that the reconciliation gate is required |
| Restore of the pre-B1a backup | Back to the demo schema and data exactly (the fallback for a failed B1a window) |

The disposable-copy dumps and restores used the documented `pg_restore`
options (`--no-owner --single-transaction --exit-on-error`) inside the
container. The `scripts.db_recovery` tool itself is exercised by
`make backup-restore-check`.

## 7. Authentication and BFF

All verified locally.

**API token checks (AUTH-1–AUTH-25).** The API answers 401 with a generic body
to every one of these tokens:
- forged, or signed with another key;
- `alg: none`;
- HS256 using the issuer's public key as the secret (key confusion);
- wrong issuer, or the issuer without its trailing slash;
- wrong audience, or the client id used as the audience;
- expired, or not yet valid (`nbf`);
- typ `JWT` instead of `at+jwt`, or carrying ID-token claims;
- from a non-allow-listed client, or with `client_id` and `azp` disagreeing;
- missing `jti` or `client_id`, an empty subject, or an unknown key.

The API also sends no CORS grant and publishes no schema.

**Web sign-in (WEB-1–WEB-19).**
- `/auth/login` and `/auth/signup` send state, PKCE S256 and the audience.
  Sign-up adds `screen_hint=signup`.
- Redirect parameters are ignored.
- These callbacks fail: wrong state, no transaction cookie, an expired
  transaction, a PKCE mismatch (the provider refused it), a replayed code, and
  a cancelled sign-in.
- Cookies are `__Host-`, HttpOnly, Secure and SameSite=Lax, and opaque.
- Logout is POST-only and same-origin, clears both cookies and ends the
  provider session.
- An expired session shows as signed out or "session ended".
- Signed-in pages are `private, no-store` (self-hosted) with no token in them.
- Headers: a nonce CSP without `unsafe-*`, `frame-ancestors 'none'`, HSTS,
  nosniff, `no-referrer` and DENY.

**BFF (BFF-1–BFF-26).** These are refused:
- cross-origin requests, and `Origin: null` with cross-site fetch metadata;
- requests with no origin information at all;
- form and text bodies (415);
- bodies over 16 KiB (413);
- missing, expired or tampered sessions (401);
- malformed JSON (400);
- unknown fields (422, never forwarded);
- a malformed Company id (403, never forwarded).

Same-origin requests, and `Origin: null` with `Sec-Fetch-Site: same-origin`,
work. Backend outcomes are mapped as follows:
- 401 → 401;
- 403 → 403;
- registration disabled → 404;
- API down → 503;
- API frozen → 503 after the timeout, never a hang.

Every response is `no-store` and carries fixed codes only.

The browser cannot reach the API at all: CSP `connect-src` blocks it, it has no
token, and the API sends no CORS grant (UI-10–UI-11). No access token appears
in HTML, storage, readable cookies or any requested URL (UI-9). None of the
run's tokens, cookies or subjects appears in the API or web logs (LOG-1–LOG-4).

**Not run through the real stack:** backend 422 and 5xx mapping. A valid BFF
request cannot provoke them, because the BFF validates exactly as the API does.
Unit tests cover them (`bff.test.ts`).

## 8. Browser and accessibility

All verified locally in headless Chrome. Screenshots are in the run's output
folder.

- **Founder journey through the hosted sign-up** (UI-1–UI-8). Validation focus
  works, what the founder entered is stored exactly, the ready page and
  workspace show correctly, and settings saves.
- **Double submission and lost responses** (UI-12–UI-14b).
  - A triple click sends one request.
  - A response lost after the server completed shows "couldn't confirm", never
    success.
  - A retry with edited details lands on "You already have a workspace" with
    the stored name, never claiming the edits were saved.
  - A demoted founder submitting again sees their existing workspace.
- **Disabled and refused** (UI-15–UI-17): registration disabled, and a
  suspended founder.
- **Jurisdiction display** (UI-30–UI-32).
  - The workspace shows exactly the API's readiness for each of: confirmed
    DIFC, unsupported ADGM, not sure, Other without an authority, and no
    answer.
  - Licensing offers exactly DIFC, Other and "I'm not sure", with free text
    for the authority.
  - There is no quiz and no invented authority list.
- **Layout and accessibility** (A11Y-1–A11Y-11).
  - At 320, 375, 390, 768, 1024 and 1440 px on the workspace, chooser,
    settings, onboarding and ready screens: no horizontal scroll, no header
    overlap, targets of at least 44 px, labelled controls, one h1 per page.
  - Keyboard: the first Tab stop is the visible skip link; the switcher and
    the mobile menu work with Enter and Escape and return focus; submitting by
    keyboard shows an announced, described error.
  - Reduced motion is honoured, and 200 % zoom causes no horizontal scroll.
- **Not run:** a real screen-reader pass (no screen reader available here;
  automated checks are no substitute). Browsers other than Chrome.

## 9. Read-only inventory of the live demo (for the runbook)

| Observation | Value |
| --- | --- |
| Vercel Production | `db03f83` (M1-10D) since 2026-10-13 22:39Z |
| Render API | `/health` 200 after a 22 s cold start; `/me/companies` 404, so older than M1-10C; `/openapi.json` 404 |
| Auth0 issuer (public discovery) | `https://heroos-demo.eu.auth0.com/`, PKCE S256, RP-initiated logout |
| Live web | "Get started" → Auth0 sign-up; signed out `/workspaces` → "Please sign in"; pages `public, max-age=0, must-revalidate` with `x-vercel-cache: HIT`, yet a fresh CSP nonce per response |

Not readable without the private control planes, and recorded as unverified in
the runbook:
- Render Auto-Deploy and the commit it serves;
- the Supabase revision;
- the Render and Vercel environment variables;
- the Auth0 sign-up and e-mail settings.

## 10. Pending approvals and decisions

Engineering is not authorized to take any of these:

1. **Merge** of this PR (Technical Lead).
2. **Staging** gates S1–S12, then each step: backup and restore check,
   B1a → API `169261d` → B1b → C1 → current API, then appointing the demo
   administrators. Each step needs its own approval
   ([runbook](../staging-activation.md)).
3. **Operator login creation:** after the operator activation checklist. It
   is blocked on a read path for the independent audit review.
4. **Sign-up activation**, a separate approval:
   - Auth0 sign-up, password and e-mail verification policy, and abuse
     controls;
   - `HEROOS_SELF_REGISTRATION_ENABLED=true` on Render;
   - JJ's privacy approvals (ADR-010 §8; PRIV-005, PRIV-008, PRIV-018,
     PRIV-020).
5. **JJ decisions** (none assumed):
   - jurisdiction confirmation criteria;
   - the licensing-authority list;
   - the quiz;
   - one self-service Company per person;
   - reactivation of a confirmation on a reverted answer (F9);
   - e-mail verification before registration (F8).
6. **Staging test matrix** ST-01 to ST-22
   ([matrix](../staging-e2e-test-matrix.md)), after the above.

No staging validation item is complete. Real Auth0 sign-up, e-mail
verification, the shared migration, the updated Render API, the updated Vercel
web, a real founder sign-up, staging isolation, staging audit events and the
activation prerequisites all remain open.
