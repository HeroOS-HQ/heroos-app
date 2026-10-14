# Staging End-to-End Test Matrix (real services, after approval)

**Status:** Prepared in M1-10E. **None of these tests has been run.** They need
the deployed services of the [staging activation runbook](staging-activation.md),
each under its own approval.\
**Data:** Synthetic only. Company names start with `[SYNTHETIC STAGING]`;
identities are throwaway mailboxes the Technical Lead controls. Subjects
(pseudonymous) are recorded in the issue, never in Git or in reports.\
**Local equivalent:** the check IDs in the last column ran locally against
real components with a local provider ([report](reports/2026-10-14-m1-10e-security-e2e-validation.md)).
A local pass is not a staging pass.

Approval keys:
- **D**: deployment steps C1–C5 / D1–D7 approved and done.
- **S**: sign-up activation (runbook section E) approved and done.
- **O**: an operator login exists (activation checklist complete).
- **J**: a JJ decision is needed first.

| ID | Test | Preconditions and identity | Action | Expected | Evidence to capture | Cleanup | Needs | Local check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ST-01 | Real Auth0 hosted sign-up | Fresh mailbox F1 | Homepage → Get started → Auth0 sign-up | Auth0's sign-up screen; back on `/onboarding`; no Company exists yet | Screen recording; `company_registrations` count unchanged | Suspend F1's User after the run | D, S | UI-1–UI-3 |
| ST-02 | E-mail verification behaviour | F1 before and after verifying | Sign in before verifying | Matches the decided policy (Auth0 enforces it; HeroOS does not check `email_verified`) | Auth0 log entry; app outcome | As ST-01 | D, S, J | not testable locally |
| ST-03 | New founder registration | F1 signed in | Complete the three steps, Create my workspace | "Your workspace is ready"; Company, Blueprint, User, binding, one `company_admin` Membership, one registration row, `company_registered` audit row | SQL (owner, read-only) per runbook F2; screenshot | Suspend F1; record the Company id | D, S | R1-1–R1-10, UI-5–UI-8 |
| ST-04 | Retry and timeout safety | F1 | Double-click Create; reload during submit; submit again later | One Company; the retry says the existing workspace wasn't changed | Network log; SQL counts | — | D, S | R2, R3, R4, UI-12–UI-14 |
| ST-05 | Workspace discovery on Render | F1 | Sign out and in | Lands on own workspace (single) | Screenshot; API log line (no subject) | — | D | R1-9 |
| ST-06 | Settings update through Vercel | F1 (admin) | Edit industry and licensing; save | "Changes saved"; readiness from the API | SQL; screenshot | — | D, S | UI-8, J-7 |
| ST-07 | Two founders, isolation | F1, fresh F2 | F2 registers; F1 opens F2's workspace, settings and ready URLs; F1 sends a PATCH via the BFF | Access denied pages; BFF 403; no F2 data in any response | HAR (no cookies kept), screenshots | Suspend F1, F2 | D, S | D-1–D-9, UI-18, BFF-14 |
| ST-08 | Registration disabled | Flag `false` | F3 completes onboarding | "Workspace setup isn't available yet"; nothing created | SQL counts | Flag back per plan | D (+S to re-enable) | R7, UI-15, BFF-19 |
| ST-09 | Existing demo accounts after migration | Demo alpha and beta | Sign in; open own and other workspace | Own as member; other denied | Screenshots | — | D | MIG-18, MIG-21 |
| ST-10 | Member vs administrator | Demo alpha before and after D7 | PATCH before and after `set-role` | 403, then 200; audit row | SQL; responses | — | D, O | D-12–D-17, MIG-20, MIG-22 |
| ST-11 | Revoked Membership | Synthetic member M1 | Operator `revoke-membership` while M1 has the workspace open; M1 saves and reloads | Save refused; reload shows no access; discovery empty, without sign-out | SQL; screenshots | Leave revoked | D, O | D-20, UI-23–UI-25 |
| ST-12 | Suspended User | F2 | Operator `suspend-user`; F2 retries everything | Neutral welcome; registration refused; no workspace | Screenshots | — | D, O | R8-4–R8-6, UI-16–UI-17 |
| ST-13 | Session expiry | F1 | Wait for the access-token expiry (or a short-lived token configured for the test) | "Your session has ended"; BFF 401 | Screenshot | — | D | WEB-16–WEB-17, UI-29 |
| ST-14 | Invalid or forged authorization | Any | Send forged, expired, wrong-audience and other-client tokens straight to the API | All 401 with the generic body | Status codes only | — | D | AUTH-1–AUTH-25 |
| ST-15 | CSRF and security headers | F1 | Cross-origin POSTs to `/bff/*` and `/auth/logout`; inspect headers | 403; nonce CSP, HSTS, DENY, no-referrer | Responses | — | D | BFF-1–BFF-12, WEB-13, WEB-19 |
| ST-16 | Jurisdiction: unconfirmed and unsupported | F1 (DIFC), F4 ("Other: Abu Dhabi Global Market") | Operator confirms F4 as `adgm` (synthetic only) | F1: not yet confirmed; F4: "ADGM isn't supported yet", no guidance | Screenshots; API JSON | Clear the confirmation | D, O, J (never for real customers) | J-1–J-12, UI-30 |
| ST-17 | Responsive browser check | F1 | 320–1440 px on the main screens | No overflow or overlap; 44 px targets | Screenshots | — | D | A11Y-1–A11Y-9 |
| ST-18 | CSP console inspection | F1 | Load workspace, settings, ready and home 10× each with DevTools open | No CSP violation, no hydration error | Console export | — | D | CSP-1–CSP-6, CSP-R1–R3 |
| ST-19 | Back after sign-out on Vercel | F1 | Sign out, press Back | No workspace content; the page reloads to "Please sign in" | Screen recording; response `Cache-Control` | — | D (M1-10E deployed) | UI-27, UI-27v |
| ST-20 | Audit records | After ST-03–ST-16 | Run the runbook F2 report queries | Every change has its event, actor and reference | Report (no subjects) | — | D, O | R1-7, J-6, D-19, MIG-22 |
| ST-21 | Recovery procedure | Scratch database only | Restore the S6 backup into a scratch database; run the §5 validation; run the reconciliation gate on paper | Validation passes; revoked access reappears and is caught by the gate | Validation output | Drop the scratch database | D (backup approval) | MIG-25–MIG-29 |
| ST-22 | Logs | After all tests | Search Render and Vercel logs for tokens, cookies and subjects | None | Search terms and counts | — | D | LOG-1–LOG-4 |
