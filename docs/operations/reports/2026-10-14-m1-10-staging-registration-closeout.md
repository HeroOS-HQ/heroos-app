# M1-10: Staging Founder Registration: Close-out Record (2026-10-14)

**Scope:** the gated rollout of founder self-registration on the temporary staging demo, and its end-to-end verification (G1–G9).\
**Environment:**
- Vercel web: `main` `61bf022`.
- Render API: `0673546`. The Live commit still has to be recorded from the Render dashboard (§11).
- Supabase project `heroos-app`: PostgreSQL 17.11 at Alembic `3f6c2a9d81b4`.
- Auth0 tenant `heroos-demo`.

**Data:** synthetic only. Company names start with `[SYNTHETIC STAGING]`.\
**Secrets:** this record contains none. It holds no credentials, tokens, subjects, e-mail addresses or database URLs. Internal IDs are listed where they are evidence.\
**Approvals:**
- Every shared-system step had its own explicit approval from the Technical Lead.
- Auth0 and Render dashboard changes were made by the Technical Lead.
- JJ's interim staging policy was relayed by the Technical Lead (§8).

**Related:**
- [Staging activation runbook](../staging-activation.md)
- [Staging test matrix](../staging-e2e-test-matrix.md)
- [M1-10E local validation report](2026-10-14-m1-10e-security-e2e-validation.md)
- [Identity Provisioning](../identity-provisioning.md)
- [Company Registration](../company-registration.md)

Status key:
- **Passed:** run on the live staging services, with evidence.
- **Blocked:** needs the operator login (§9).
- **Not run:** the reason is stated.

## 1. Summary

Founder self-registration works end to end on staging, with invitation-only sign-up:

- an invited synthetic founder signs up through Auth0;
- verifies their e-mail address;
- completes onboarding;
- gets a new Company where they are its only `company_admin`.

The migrations B1a, B1b and C1 were applied by exact revision. Each step was:
- backed up beforehand, and the backup validated;
- rehearsed on a restored copy of the live data;
- verified before and after.

The API was moved through the compatible generations (`169261d`, then `0673546`) without exposing an incompatible schema.

Two synthetic founders registered (F1, F2). Every database, API and browser check passed:
- 18/18 database postcondition checks;
- 31/31 unauthenticated API and web smoke checks;
- 0 monitoring anomalies.

Tests that need an operator login stay **blocked** (§9). Four limitations are **accepted for staging**, not solved (§7).

## 2. Final state (2026-10-14, after G9)

| Component | State | Evidence |
| --- | --- | --- |
| Supabase schema | `3f6c2a9d81b4`, `heroos_schema_contract()` = 3 | 18/18 catalog and data checks |
| Data | 4 Companies, 4 Users and 4 identity bindings (one issuer), 4 Memberships, 2 self-registrations. 2 `company_admin` (the founders); the 2 demo users are `member`. 0 confirmed jurisdictions | Daily review |
| Audit | 6 identity, 2 Membership and 2 Company events. Each belongs to one of the two registrations or to the B1a backfill | Reference reconciliation |
| Render API | `0673546` (M1-10E); `HEROOS_SELF_REGISTRATION_ENABLED=true` | Registration answers 401 without a token, and 404 when disabled |
| Vercel web | `61bf022` (PR #23) | Production deployment success at 15:29:33Z |
| Auth0 | Invitation-only sign-up (Pre User Registration allow-list). Post Login Action denies unverified e-mail addresses for the web client. No social connection on the app. Logout confirmation on | Technical Lead tests (G7); hosted pages show no social buttons |
| Attack Protection | Deferred: accepted limitation | §7 |

## 3. Gate log

All times are UTC on 2026-10-14.

| Gate | What | Result |
| --- | --- | --- |
| G1 | Read-only logical backup (schema `public`) at `97d4200fe7a2` | 24,490 B, sha256 `f124fdf2…` |
| G1 | Validation and rehearsal | Restored into a throwaway PostgreSQL 17 with identical data. B1a→B1b→C1 rehearsed on the restored copy as the non-superuser owner |
| G2 | B1a `b8a11c15ed91`, 09:36Z, with `-x legacy_identity_issuer`/`-x legacy_identity_user_count=2` | Contract 1. 2 bindings with the exact issuer, subjects equal to the legacy column, data byte-identical. The old API's access pattern was unchanged |
| G3 | API `169261d` | Deployed by the Technical Lead; its startup contract check was observed at 09:49Z |
| G4 | B1b `09cb5ec569b9`, 10:31Z | Contract 2. Legacy column dropped. Operator grants as designed, with 0 operator members. The `371dd50` query shape now fails closed |
| G5 | Fresh backup at `09cb5ec569b9` | 53,178 B, sha256 `23f84aea…`, validated |
| G5 | C1 `3f6c2a9d81b4`, about 11:47Z | Contract 3. Nobody promoted, nothing confirmed. Registration and discovery functions are `SECURITY DEFINER` with `search_path=''` and runtime-only EXECUTE. 14 triggers, RLS on 12 tables |
| G6 | API `0673546` | Deployed by the Technical Lead. `/me/companies` 401; demo users see their own Company as member and cannot reach another Company |
| G7 | Auth0 changes by the Technical Lead | Verified-e-mail Action and invitation-only sign-up |
| G7 | PR #23 merged → `61bf022` | Fixed verify-email notice with "Sign in again" and "Use a different account" |
| G8 | Fresh backup at `3f6c2a9d81b4`, 18:44Z | 82,683 B, sha256 `00351a7c…`, validated |
| G8 | Flag set on Render by the Technical Lead | Registration 401 (was 404). Smoke 31/31. 0 registrations before G9 |
| G9 | Live tests T1–T4, 19:01Z–19:46Z | §4 |

## 4. G9 end-to-end results

| Test | Run | Result |
| --- | --- | --- |
| 1. Homepage → Get started → Auth0 sign-up | T3 (F2) | Passed |
| 2. Unverified e-mail gets no access | G7, T3 | Passed. Verify-email notice shown. No HeroOS row existed before the registration (the User was created by it; no earlier event) |
| 3. Verified founder signs in and opens onboarding | T1 (F1) | Passed |
| 4. Company details, licensing, review | T1 (DIFC), T3 (Other / `MOHRE`, entered on purpose instead of the planned text) | Passed. Stored values equal the entered values |
| 5. "Create my workspace" creates User, binding, Company, Blueprint, `company_admin` Membership, registration and audit | T1, T3 | Passed. One of each, with exact issuer. 4 audit events per registration (`company_registered`, `membership_granted`, `user_created`, `identity_bound`), actor `api` / `heroos_app` / `registration:<id>` |
| 6. Sign out and in: same workspace | T2 | Passed |
| 7. Double submit or retry: no duplicate | T1, T2 | Passed. In T1 two submissions reached the API, the second answered "existing" (§6). In T2 revisiting onboarding did not submit |
| 8. F1 cannot read or edit F2's Company | T4 | Passed. Pages denied, BFF PATCH 403, F2's Blueprint byte-identical |
| 9. Member vs administrator | T4 | Passed. F1 saved its own settings; a demo member was refused |
| 10. Unconfirmed jurisdiction gives no guidance | T1, T3, T4 | Passed. No jurisdiction or confirmation field set |
| 11. Back after logout | T4 | Passed |
| 12. No cached private HTML, token leak or CSP warning | T4 | Passed (Technical Lead's browser check). Cache-Control value not recorded (§11) |

T4 database comparison against the T3 baseline:
- F2's Blueprint and both demo Blueprints are byte-identical.
- F1's Blueprint changed only in `industry` (with `updated_at`): reverting those two fields reproduces the baseline hash.
- Exactly one Blueprint update reached the database.
- No new row, Membership, role change or audit event.

Registrations (synthetic):

| Founder | Company | Registration | Licensing |
| --- | --- | --- | --- |
| F1 | `4280a76d-4e6d-4436-b491-2615bff3568a` | `eb773ff4-7cdf-459a-a553-94283a6017ab` (19:01:44Z) | DIFC, unconfirmed |
| F2 | `0ae226ea-585e-499b-863b-820b4bafa4e9` | `81eaa911-a421-4ab6-b31c-0b86b1812c6d` (19:27:42Z) | Other / `MOHRE`, unconfirmed |

Staging matrix:

| Status | IDs |
| --- | --- |
| Passed | ST-01, ST-02, ST-03, ST-05, ST-06, ST-07, ST-09, ST-15, ST-18, ST-19 |
| Passed in part | ST-04: retry safety live; a forced timeout was not induced. ST-14: forged, `alg=none` and Basic tokens refused; expired and wrong-audience tokens not minted live. ST-20: every API audit event reconciled; operator events blocked. ST-21: three backups restored and validated in throwaway databases; no full Supabase restore (§7) |
| Blocked (operator login) | ST-10, ST-11, ST-12, ST-16 |
| Not run | ST-08 in the browser: would need the flag off again; the API's 404 was verified before activation. ST-13: one-hour wait; covered locally (UI-29). ST-17: covered locally (A11Y-1–9). ST-22: needs the Render and Vercel log dashboards |

## 5. Security checks on the live services

- **Unauthenticated access.**
  - Every protected API route answers 401: with no token, with a forged token, with an unsigned `alg=none` token, and with a Basic credential.
  - Docs routes are 404. A foreign-origin preflight is granted nothing.
  - API responses carry `no-store`, `nosniff`, `no-referrer`, `DENY`, `default-src 'none'` and HSTS. The 401 body is generic.
- **Web BFF.** A foreign origin gets 403 and a missing session gets 401. Signed-out workspace and settings pages show the sign-in gate. Pages carry a nonce CSP and HSTS.
- **Tenant isolation**, replayed as the API runtime login (read-only, rolled back):
  - each founder discovers only their own Company;
  - no row of another Company is visible in a tenant scope, and nothing at all without one;
  - the runtime login cannot write identity tables or read audit or registration tables.
- **Logout.**
  - Auth0 advertises `end_session_endpoint`. The web sends `client_id` and `post_logout_redirect_uri`; Auth0 accepts that URL (302) and refuses an unregistered one (400).
  - Auth0 shows its logout confirmation because no `id_token_hint` or `logout_hint` is sent. It stays enabled.

## 6. Findings and observations

| # | Finding | Status |
| --- | --- | --- |
| O-1 | T1: the registration function ran twice (about 38 ms create, about 4 ms "existing"). The wizard locks after a success, so the second call was a separate submission; the cause is not visible server-side | Closed. Idempotent, no duplicate. T3's single submission made exactly one call |
| O-2 | A request with malformed JSON gets a generic 422 before authentication on every JSON route. The body is not echoed and no data is reached | Informational |
| O-3 | e2e UI-4 (focus after validation) raced `requestAnimationFrame` once on a CI runner | Open (test-only follow-up) |
| O-4 | Restoring a Supabase archive as the non-superuser owner fails unless the `DEFAULT ACL … supabase_admin` and `SCHEMA public`/`COMMENT` entries are excluded with `pg_restore -L` | Open. Add to [Backup and Recovery](../../architecture/backup-and-recovery.md) |
| O-5 | The API exposes no build identifier and Render publishes nothing to GitHub, so the Live API commit cannot be verified from outside | Open (§11, §12) |
| O-6 | A denied unverified sign-in showed only "Sign-in was cancelled." | Fixed by PR #23 |

## 7. Accepted limitations (staging only; not completed controls)

1. **Auth0 Attack Protection deferred** to the production security work. Mitigation: invitation-only sign-up and verified e-mail before any token.
2. **No full Supabase restore drill.** Logical backups were restored and validated only in throwaway PostgreSQL 17. Cluster roles and the runtime password would have to be recreated. The reconciliation gate ([Identity Provisioning §6](../identity-provisioning.md)) has not been rehearsed. RTO is unmeasured.
3. **No HeroOS-side suspension** until the operator login exists (§9). The per-person stop is blocking the account in Auth0. The web session then ends within 1 hour, and HeroOS rows stay.
4. **Owner credential exception** (Technical Lead decision, 2026-10-14):
   - The Supabase migration-owner credential stays on the Technical Lead's operations host, not in Git, Render, Vercel or CI.
   - It is used for the read-only daily registration review, which needs the only role that can read the registration and audit tables.
   - Scope is not to be expanded. **End date: to be set by the Technical Lead.**
   - Also to record in the activation issue as the interim exception to the ADR-008 owner scope.
5. Operational, not security:
   - Auth0's built-in test e-mail provider has low sending limits.
   - Render's free tier cold-starts in about 20 s, longer than the web's 10 s timeout: warm `/health` before demonstrations.

## 8. Approvals recorded

- **JJ** (relayed by the Technical Lead, 2026-10-14; JJ's own written record and date not provided):
  - interim staging policy for synthetic founder registration;
  - one self-service Company per person;
  - temporary privacy, retention and deletion arrangements: no deletion capability, suspend or block instead, and staging data destroyed when the staging environment is retired;
  - registration limited to approved synthetic testers.
- **Technical Lead:**
  - G1–G9 step by step;
  - F1 and F2 kept as approved synthetic demo accounts;
  - invitation-only registration kept enabled for controlled demonstrations;
  - operator-dependent tests kept blocked;
  - branch and worktree cleanup deferred until this record is final.

## 9. Remaining operator dependencies

The operator login is not created until the [activation checklist](../identity-provisioning.md#operator-activation-checklist) is complete. Open items:
- the authorized audit-report read path (exception to the migration-owner scope);
- JJ's named independent reviewer;
- the report storage location;
- JJ's written approval of D1–D6 and R1–R3 linked from the policy.

Blocked until then:
- staging tests ST-10 (set-role before and after), ST-11 (revoked Membership), ST-12 (suspended User), ST-16 (jurisdiction confirmation; also needs JJ's confirmation criteria), and the operator events of ST-20;
- runbook D7: administrators for the two demo Companies, which stay `member`;
- runbook F5: suspending or revoking test identities after testing.

## 10. Emergency registration disable

| Need | Action | Effect | Verify |
| --- | --- | --- | --- |
| Stop new registrations | Render → API service → Environment: `HEROOS_SELF_REGISTRATION_ENABLED=false` (or delete it) → **Save and deploy** (no rebuild) | `POST /company-registrations` answers 404 within the deploy (minutes). Existing workspaces keep working | Unauthenticated `POST /company-registrations` answers 404; the database registration count stops growing |
| Stop new accounts | Auth0: empty the invitation allow-list secret of the Pre User Registration Action → Deploy, or turn on "Disable Sign Ups" | Every sign-up is refused at once | A sign-up attempt shows the invitation-only message |
| Stop one person | Auth0 → User Management → the user → Block | No new tokens; the web session ends within 1 hour | Auth0 log shows the blocked login |
| Everything | Render: suspend the API service | API offline; the web shows "temporarily unavailable" | `/health` fails |

Nothing is deleted by any of these. Record each use in the activation issue.

**Monitoring.** A daily read-only review covers:
- totals, new registrations, audit events by type and actor;
- anomalies: more than one registration per User, foreign issuer, registration without audit, role changes;
- Auth0's sign-up log.

It runs as the migration owner under the exception in §7, prints internal IDs and counts only, and showed 0 anomalies after G9.

## 11. Missing evidence (to be supplied by the Technical Lead)

1. **Live Render API commit.** Render → API service → Events: the Live deploy's SHA. Expected `0673546`. The API code in `0673546` and `61bf022` is identical, so either is functionally the same, but it must be recorded.
2. **F1 industry value.** The stored value is a 10-character value. It is neither the original nor the planned `Synthetic testing T4`, and was presumably typed on purpose. Only that field changed.
3. **Authenticated-page `Cache-Control`.** The header of one signed-in page, from the browser's Network panel.
4. Optional:
   - T1's `POST /bff/registrations` count and status codes;
   - T1's ready-page wording;
   - the Render and Vercel log search for tokens, cookies and subjects (ST-22).

## 12. M1 issue status

**Complete:**
- M1-01 to M1-08 and the M1-09 close-out ([M1 close-out](../../milestones/m1-foundation-security-closeout.md)).
- M1-10 (HER-230):
  - sub-issue 01, the architecture audit;
  - M1-10B identity and provisioning (PR #16): merged, B1a and B1b applied to staging;
  - M1-10C Company registration and administrators (PR #20): merged, C1 applied;
  - M1-10D onboarding and workspace UI (PR #21): merged and live;
  - M1-10E security and end-to-end validation (PR #22): merged and live;
  - staging activation (runbook C, D and E) executed, except D7;
  - the follow-up PR #23 (verify-email notice).

**Open:**
- Operator activation (§9): JJ checklist items, then the operator login, demo administrators (D7), and ST-10, ST-11, ST-12 and ST-16.
- ADR-008 and ADR-010: technical status still "Proposed". Acceptance is a Technical Lead decision, now that both are deployed.
- JJ decisions:
  - jurisdiction confirmation criteria, licensing-authority list, quiz;
  - final PRIV-005, PRIV-007, PRIV-008, PRIV-018 and PRIV-020 (interim approved);
  - PRIV-013, PRIV-017 and PRIV-019 (production).
- Documentation drift:
  - the [third-party service inventory](../../privacy/third-party-service-inventory.md) still lists Render and Vercel as planned and the demo OpenID Provider as "Decision Required" (now Auth0, with invited testers' e-mail addresses);
  - O-4 for the backup document.
- Engineering follow-ups:
  - O-3 (UI-4 flake);
  - O-5 (expose a build identifier on the API);
  - API settings do not themselves enforce `sslmode=verify-full` on the database URL (HER-230 audit item; the deployed configuration uses it);
  - a production e-mail provider and Attack Protection (production security work);
  - a deletion capability (PRIV-020);
  - removal of the owner credential exception at its end date.
- M1-10F (demo readiness and AWS path) was named in earlier planning. It is not in the repository; confirm its scope.

**Suggested next priorities:**
1. Operator activation. This unblocks D7, suspension and the blocked tests; it needs JJ's checklist items first.
2. Housekeeping: ADR-008 and ADR-010 acceptance, the service inventory, O-4, and the missing evidence (§11).
3. Small hardening: build identifier (O-5), `sslmode` enforcement, UI-4 test wait.
4. M2 product work on the now-working onboarding path.
