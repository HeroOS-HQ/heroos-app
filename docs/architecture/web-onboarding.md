# Customer Onboarding and Workspace UI (M1-10D)

**Status:** Implemented on `feature/m1-10d-onboarding-workspace-ui`; tested against a local mock of the M1-10C API only. Nothing deployed, no provider setting changed\
**Owner:** Technical Lead\
**Related:** [Company Registration runbook](../operations/company-registration.md),
[ADR-010](../decisions/ADR-010-company-registration-and-administrators.md),
[Authentication §10](authentication.md#10-browser-access-b4),
[Security Boundaries](security-boundaries.md)

The web app (`apps/web`) lets a signed-in founder create their company
workspace, and lets every user open the workspaces the API authorizes for them.
It builds on the merged M1-10C API (`f2f1325`) and changes nothing in the API,
the database or the identity provider.

## 1. Routes

| Route | What it does | Signed out |
| --- | --- | --- |
| `/` | Marketing homepage (M1-11 owns its redesign). "Get started" → `/auth/signup`, "Sign in" → `/auth/login`. A signed-in visitor is sent to `/workspaces` | Homepage |
| `/auth/signup` | Same Authorization Code + PKCE flow as `/auth/login`, plus `screen_hint=signup` (OIDC only); after the callback the user lands on `/onboarding` | — |
| `/auth/login`, `/auth/callback`, `POST /auth/logout` | Unchanged (Authentication §10.2), except that the login transaction now records where to land | — |
| `/workspaces` | Workspace discovery: one workspace → redirect to it; several → chooser; otherwise a state page (§3) | "Please sign in" |
| `/onboarding` | The three-step setup (§4) | "Create your account to get started" |
| `/workspaces/{id}` | Company workspace: name, role, welcome, Company information, jurisdiction readiness, setup checklist, HR workflows marked "Coming soon", read-only case list | "Please sign in" |
| `/workspaces/{id}/ready` | After a confirmed registration only. `?outcome=existing` only changes the wording; all data is read back from the API | "Please sign in" |
| `/workspaces/{id}/settings` | Company profile: administrators edit, members see it read-only | "Please sign in" |
| `POST /bff/registrations` | BFF for `POST /company-registrations` | 401 |
| `PATCH /bff/companies/{id}/blueprint` | BFF for `PATCH /companies/{id}/blueprint` | 401 |

The Company id in a URL is only a resource identifier: every page asks the API,
which authorizes the request (Membership and RLS). A malformed id is refused
before any API call and shows the same "no access" page as another Company's id.

## 2. Sign-up entry

`/auth/signup` reuses the login flow with a fixed `screen_hint=signup`, which
Auth0's Universal Login reads to open on its sign-up form. Other OpenID
Providers ignore unknown authorization parameters (RFC 6749 §3.1), and the
Cognito path never sends it. The landing path (`/onboarding` or `/`) is sealed
in the single-use login cookie, so it cannot be chosen by a URL parameter.

Whether anyone can actually create an account is the provider's setting.
Public sign-up is disabled in the demo tenant, so today the hosted page only
signs in existing accounts. Email verification is the provider's policy:
HeroOS does not verify email addresses, and the web app makes no claim that an
address is verified.

## 3. State model

Each signed-in page derives its state from the API's answers, server-side
(`src/lib/server/app-state.ts`):

| API answer | State | UI |
| --- | --- | --- |
| No or invalid session cookie | `SIGNED_OUT` | Sign-in prompt (onboarding: create an account or sign in) |
| Missing or invalid web configuration | (not configured) | "Sign-in isn't set up here" |
| 401 from any call | `SESSION_EXPIRED` | "Your session has ended", sign in again |
| `GET /me/companies` 403 | `AUTHENTICATED_UNPROVISIONED` (indistinguishable from a blocked identity) | Neutral welcome with one "Set up my company" link. The 403 is **not** proof of eligibility; only the registration API decides |
| `GET /me/companies` 200 `[]` | `NO_ACTIVE_WORKSPACE` | "No active workspace". An empty list is a known account whose access was removed, not a new founder; setting up a new company is offered as a secondary action only |
| `GET /me/companies` 200, one | (redirect) | Straight to that workspace |
| `GET /me/companies` 200, several | `WORKSPACE_SELECTION` | Chooser with roles |
| Company 403/404 | `ACCESS_DENIED` | One message for another Company, a revoked Membership or an unknown id |
| Company 200 | `WORKSPACE_READY` | Workspace |
| Membership `company_admin` / `member` | `PROFILE_EDITABLE` / `PROFILE_READ_ONLY` | Settings form, or "View only" |
| 5xx, timeout, malformed response | `API_UNAVAILABLE` | "We can't reach HeroOS right now", try again |

Responses are parsed strictly: an unexpected shape is treated as unavailable,
never shown partially.

## 4. Onboarding and registration

Three steps, held in the browser's memory only (no storage, no URL
parameters). Leaving with unsaved details asks for confirmation.

1. **Company details.** Company name (required); legal business name,
   industry and number of employees (optional). Text is trimmed and checked like
   the API does (length: 200, 200, 120; no control, format or line-separator
   characters). Employees: a whole number from 0 to 10,000,000.
2. **Licensing** (§6).
3. **Review**, then **Create my workspace**. This is the only step that sends
   anything. Nothing is ever submitted automatically, and a second click while
   a request is in flight is ignored.

The browser posts the draft to `POST /bff/registrations`. The web server
validates it strictly, rebuilds the body field by field, and calls
`POST /company-registrations` with the session's token:

| API answer | Web outcome |
| --- | --- |
| 201 `created` | `/workspaces/{id}/ready`: "Your workspace is ready" |
| 200 `existing` | Same page, "You already have a workspace": the submission changed nothing and the details on record are shown, read back from the API. The wording stays true even when this follows a retry of an uncertain first attempt that did create the workspace |
| 401 | "Your session has ended". The draft is not kept |
| 403 | "We couldn't create a workspace for this account" (suspended or removed access) |
| 404 | "Workspace setup isn't available yet" (`HEROOS_SELF_REGISTRATION_ENABLED` is off, or an API older than M1-10C) |
| 422 | "Some details need attention", with the fields the API named, mapped back to the form |
| 5xx, timeout, network error | "We couldn't confirm that your workspace was created". Retrying is safe because registration is idempotent per person; "Check my workspaces" is offered too |

"Success" appears only after a 201 or 200 whose body names a Company id. The
ready page then loads that Company through the API like any other workspace.

## 5. Discovery, switching and settings

- **Discovery** uses `GET /me/companies`. `HEROOS_DEMO_COMPANY_IDS` is now an
  optional fallback, used only when the API answers 404 for `/me/companies` (an
  API older than M1-10C). Even then each candidate is authorized by the API.
- **Switching**: with more than one workspace, the header shows "Switch
  company" (Escape and outside clicks close it). Every switch is a full page
  load, so nothing from the previous Company stays in client state or the
  router cache.
- **Settings**: administrators edit legal name, industry, employee count and
  licensing. Only changed fields are sent (`PATCH`), "Changes saved" appears
  only after the API confirms, and the jurisdiction readiness is refreshed from
  the API's answer. If the saved jurisdiction is confirmed or unsupported, a
  licensing change shows a warning that it will need confirming again. Members
  see a read-only profile. The API enforces the role on every save; the web
  form is a convenience, not the control.
- The Company name is shown but not editable (the API has no rename).

## 6. Jurisdiction UI

- Licensing choices are **DIFC**, **Other** ("any other licensing authority,
  such as another free zone or a mainland (onshore) licence") and **I'm not
  sure**. "Onshore" is a kind of Other, never a synonym for "not sure".
- **Other** offers an optional free-text authority, stored as entered and
  never interpreted. Changing the choice clears a previously typed authority.
- **I'm not sure** stays unresolved: it is recorded as `not_sure`, and the
  workspace says the licensing details can be confirmed later.
- **No quiz** and **no invented authority list**.
  `APPROVED_LICENSING_AUTHORITIES` in `src/lib/onboarding/copy.ts` is `null`.
  When JJ approves a list, setting it switches the authority field to a select
  without any other change. The API stores text either way.
- Readiness copy follows the API's `readiness` and `reason` only:
  - "Confirmed" requires `supported_confirmed` and `guidance_allowed`.
  - `unsupported` says HeroOS doesn't currently support guidance for that
    jurisdiction.
  - Everything else is "Not yet confirmed", with a reason-specific
    explanation.
  - Creating a workspace is never presented as a legal or jurisdiction
    confirmation.

## 7. Security

- **No tokens in the browser.** All API calls are made by the web server with
  the sealed session cookie's token. Client components only call `/bff/*`.
  `src/security-boundaries.test.ts` enforces this:
  - client files import server modules for types only;
  - no token or API strings in client code;
  - no web storage and no `NEXT_PUBLIC_` variables;
  - exactly the two BFF routes exist, and both are guarded.
- **BFF guard, in order:**
  - Same origin. `Origin` must equal `HEROOS_WEB_ORIGIN`. Under
    `Referrer-Policy: no-referrer` browsers may send `Origin: null`, and then
    only `Sec-Fetch-Site: same-origin` is accepted. A request with neither is
    refused.
  - `Content-Type: application/json`.
  - A 16 KiB body limit.
  - A valid session.
  - Strict parsing: unknown keys are refused, and the body is rebuilt field by
    field.

  Responses carry fixed error codes only. API error text is never relayed, and
  every response is `no-store`.
- Route Handlers rather than Server Actions: Next.js' Server Action origin
  check rejects the `Origin: null` that `no-referrer` produces.
- **CORS is unchanged** (the browser never calls the API). The nonce CSP is
  unchanged. All styling is in classes (no inline `style` attributes).
- **Known CSP notice:** when React streams a late chunk that lands inside an
  SVG, it emits a hidden `<svg style="display:none">` container. CSP blocks
  that `style` attribute and the browser logs a violation. The nonce'd script
  that follows immediately moves the content and removes the container, so
  nothing renders differently. Allowing it would need `'unsafe-hashes'` plus
  the hash of `display:none` in `style-src`; that was deliberately not changed
  here.

## 8. Compatibility while deploying

The web can be deployed before or after the M1-10C API:

| API | Behaviour |
| --- | --- |
| M1-10C | Full behaviour above |
| Older, no `/me/companies` (404) | Falls back to `HEROOS_DEMO_COMPANY_IDS` if set, otherwise "unavailable". Missing membership and Blueprint routes give a reduced workspace without role or jurisdiction. Registration answers 404, shown as "not available yet" |

## 9. Not activated (deployment prerequisites)

None of these is done, and each needs its own approval:

1. The M1-10B/M1-10C migrations (B1a, B1b, C1) on the Supabase demo, and the
   M1-10C API on Render ([runbook §2](../operations/company-registration.md#2-deployment-order-approval-required-at-each-step)).
2. This web build on Vercel. `HEROOS_DEMO_COMPANY_IDS` can stay set during the
   transition and be removed afterwards.
3. `HEROOS_SELF_REGISTRATION_ENABLED=true` on the API, and public sign-up at the
   provider ([runbook §3](../operations/company-registration.md#3-activating-founder-self-registration-separate-approval)).
   Until then, "Get started" reaches the hosted login page, and a signed-in
   account without a Company sees "Workspace setup isn't available yet".
4. JJ decisions: the licensing-authority list, the jurisdiction confirmation
   criteria and the privacy follow-ups in ADR-010 §8. None blocks this code.

## 10. Verification

- **Unit and component tests** (Vitest, React Testing Library):
  - validation;
  - payload building;
  - every registration outcome;
  - BFF guards, including cross-origin, `Origin: null`, content type, size and
    unknown keys;
  - discovery states;
  - admin vs member settings;
  - jurisdiction copy;
  - the switcher;
  - the security boundaries.
- **Local end-to-end check** against the production build (`next build` +
  `next start` behind local TLS):
  - A mock of the M1-10C API served synthetic personas, and Chrome was driven
    over the DevTools protocol at 320–1440 px.
  - Covered: the full founder path (sign-up entry, three steps, create, ready,
    workspace, settings save) and every failure outcome.
  - Also covered: switching, member read-only views, sign-out, and headers.
  - Checks for horizontal scrolling, header overlap, 44 px targets and labels
    passed.

  The harness lived outside the repository and is not part of CI.
- **Not verified:**
  - the real Auth0 hosted sign-up;
  - a real API and database;
  - email-verification behaviour;
  - screen readers;
  - browsers other than Chrome.

## 11. Handoff to M1-10E (security, tenant isolation, end-to-end onboarding)

Run against a test identity tenant and a disposable or demo database, after
§9 steps 1–3 are approved:

1. A new account signs up at the hosted page, lands on `/onboarding`, creates a
   Company and becomes its only `company_admin` (check `company_registrations`
   and `membership_events`).
2. A second registration by the same person, a second tab, a double click and
   a retry after a dropped connection each yield one Company.
3. A second founder never sees the first founder's Company:
   - not in `/me/companies`;
   - not via `/workspaces/{first id}` (403 page);
   - not via `PATCH /bff/companies/{first id}/blueprint` (403).
4. A member cannot change the Blueprint through the BFF, and a revoked
   Membership disappears from discovery on the next page load.
5. A cross-site page cannot submit either BFF route or log the user out
   (`Origin`, `Sec-Fetch-Site`, `SameSite=Lax`).
6. A suspended User gets the neutral welcome, then "couldn't create a
   workspace": never another person's Company.
7. Session expiry mid-onboarding shows "session ended" and creates nothing.
8. Response headers on every page: nonce CSP, `no-store` for signed-in pages,
   no tokens in HTML, storage or readable cookies.
9. Accessibility pass with a screen reader (VoiceOver or NVDA) and keyboard
   only, at 200 % zoom.
