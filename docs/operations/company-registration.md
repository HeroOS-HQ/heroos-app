# Company Registration, Administrators and Jurisdiction (Runbook)

**Status:** M1-10C merged (`f2f1325`); the M1-10D web onboarding is on a feature branch. Nothing here has been run against a deployed database or identity provider\
**Owner:** Technical Lead\
**Related:** [ADR-010](../decisions/ADR-010-company-registration-and-administrators.md),
[ADR-008](../decisions/ADR-008-external-identity-and-provisioning.md),
[Identity Provisioning runbook](identity-provisioning.md),
[Authentication](../architecture/authentication.md)

Every step that touches a deployed database, the identity provider or a
deployment needs explicit approval first. The temporary demo holds synthetic
data only.

## 1. How a Company is created

| Path | Who | When |
| --- | --- | --- |
| Founder self-registration, `POST /company-registrations` | The founder, signed in at the identity provider | The normal path, once activated (§3) |
| Operator-assisted, `register-company` | The Technical Lead (operator login) | A second Company for an existing founder, special cases, or before activation |

Both create a new Company with an empty Blueprint and exactly one
`company_admin` Membership, in one transaction, audited. Neither can attach
anyone to an existing Company.

## 2. Deployment order (approval required at each step)

The M1-10B migrations have not been applied to the Supabase demo yet. With
M1-10C merged, the zero-downtime order is:

1. Logical backup ([Backup and Recovery](../architecture/backup-and-recovery.md)).
2. B1a with the backfill arguments ([identity runbook §3](identity-provisioning.md#3-deploying-the-identity-migrations-approval-required)).
3. Deploy the API at `169261d` (M1-10B), smoke test.
4. B1b. Then C1: `uv run alembic upgrade 3f6c2a9d81b4` (as the migration owner,
   from a clean checkout). C1 keeps the M1-10B API working (proven by
   `test_company_migration.py`).
5. Deploy the M1-10C API. It refuses to start before C1 (schema contract 3).
6. Smoke test sign-in, Company access and cross-Company denial; `GET
   /me/companies` for each demo user.
7. Appoint administrators for the existing demo Companies (§4, `set-role`).
   Migration C1 made every existing Membership a `member`.

Shorter alternative: B1a, B1b and C1 in one window, then deploy the M1-10C API.
The previous API fails closed from B1b until the new one is live (a short
outage of the synthetic demo).

Rollback: roll forward. C1's downgrade refuses as soon as any registration,
role change, licensing answer, confirmation or Membership change exists.

## 3. Activating founder self-registration (separate approval)

Self-registration is off in every environment until both are switched on:

1. `HEROOS_SELF_REGISTRATION_ENABLED=true` in the API environment (Render).
   Without it, `POST /company-registrations` answers 404.
2. Public sign-up at the identity provider (Auth0: Database connection →
   "Disable Sign Ups" off; email verification as decided). Engineering does not
   change provider settings.

Before activation:

- Abuse controls at the provider (bot detection, sign-up rate limits) and the
  per-person limit (one self-service Company per HeroOS User) reviewed.
- The web onboarding (M1-10D) deployed.
- The privacy follow-ups in ADR-010 §8 acknowledged (self-registered Users
  are personal data subjects; deletion and retention are still pending).

With only step 1, accounts created by an administrator at the provider can
self-register; with neither step, only operators create Companies.

## 4. Operator commands (M1-10C)

All commands use the operator CLI exactly as in the
[identity runbook §2](identity-provisioning.md#2-using-the-cli) (operator
login, `--expect-database`, `--reference <issue key>`, subjects on standard
input). Each is one audited transaction and idempotent.

| Command | Effect |
| --- | --- |
| `register-company --company <new uuid> --name <name> --issuer <iss> [--existing-user]` (+ subject) | New Company, empty Blueprint, the identity as its `company_admin`. Generate the UUID once (`python -c 'import uuid; print(uuid.uuid4())'`), record it in the issue, and re-use it on retries: a retry answers `unchanged`; another identity is refused (`company_exists`). Without `--existing-user` a bound identity is refused (`identity_exists_use_grant`) |
| `set-role --company --membership --role company_admin\|member` | Appoint or remove a Company administrator. Refused for a revoked Membership (reactivate it first) |
| `jurisdiction-status --company` | Read-only: the customer's licensing answer and readiness |
| `confirm-jurisdiction --company --jurisdiction uae_federal\|difc\|adgm\|other --licensing-location difc\|other [--licensing-authority <name>]` | Record a reviewed Company-level jurisdiction. The stated answer must equal the customer's current one (`licensing_answer_mismatch`); "not sure" or a missing answer cannot be confirmed (`licensing_answer_unresolved`) |
| `clear-jurisdiction --company` | Withdraw a confirmation |

**Do not confirm jurisdictions for real customers** until JJ has approved the
confirmation criteria (ADR-010 §8). A confirmation records a decision; HeroOS
has no approved rule that makes it.

What the operator login **cannot** do (also after M1-10C): read the Company
name back, read or edit the Blueprint's business profile (legal name,
industry, employee count), edit the customer's licensing answer, read
`company_events` or `company_registrations`, delete anything, or call the
API's registration function.

The identity runbook's §7 (operator trust boundary) applies unchanged: these
are further things one operator login can do alone, audited.

## 5. Audit (additions to the identity runbook §8 report)

| Table | Events | Actor |
| --- | --- | --- |
| `company_events` | `company_registered`, `jurisdiction_confirmed` (with the jurisdiction code), `jurisdiction_cleared` | `operator`, `owner`, or `api` for self-registration |
| `membership_events` | adds `membership_role_changed`; every event now records the `role` | as before |
| `company_registrations` | one row per self-registration (identity, User, Company, Membership) | written only by `heroos_register_company` |

Self-registrations carry the reference `registration:<company_registrations.id>`
and the API login as `db_role`, not an issue key: they are reconciled against
`company_registrations`, not the issue tracker. Additional report sections:

```sql
-- 6. Company events in the period
SELECT occurred_at, txid, event_type, company_id, jurisdiction, actor_kind, db_role, actor_reference, id
  FROM company_events
 WHERE occurred_at >= :'period_start' AND occurred_at < :'period_end'
 ORDER BY occurred_at, id;

-- 7. Self-service registrations in the period
SELECT registered_at, id, company_id, user_id, identity_id, membership_id
  FROM company_registrations
 WHERE registered_at >= :'period_start' AND registered_at < :'period_end'
 ORDER BY registered_at, id;
```

Retention is undecided (PRIV-005); nothing purges these rows.

## 6. M1-10D integration contract

All calls are made by the web server (BFF) with the session's access token;
the browser never calls the API (CORS stays `GET`-only). Error bodies are
fixed strings and must not be rendered.

### Onboarding flow

As implemented by the web app (M1-10D; routes, states and copy in
[Customer Onboarding and Workspace UI](../architecture/web-onboarding.md)):

```text
sign in or sign up (provider) ──▶ GET /me/companies
                         ├─ 200 [..]  → the single workspace / the chooser
                         ├─ 200 []    → "no active workspace" (all Memberships revoked)
                         └─ 403       → neutral welcome; the 403 is not proof of
                                        eligibility (a blocked identity looks the same)
"Set up my company" (deliberate click) ──▶ Welcome + three-step form ──▶ "Create my workspace"
                     ──▶ POST /bff/registrations ──▶ POST /company-registrations
                         ├─ 201 created  → /workspaces/{company_id}/ready
                         ├─ 200 existing → same page, "your existing workspace wasn't changed"
                         ├─ 403          → account suspended / access revoked
                         ├─ 404          → self-registration not enabled
                         ├─ 422          → fix the named fields
                         └─ 5xx/timeout  → outcome unknown; retry is safe (idempotent)
```

### `POST /company-registrations`

Request (unknown fields are refused with 422):

```json
{
  "company_name": "Acme Trading LLC",
  "blueprint": {
    "legal_name": "Acme Trading LLC",
    "industry": "Retail",
    "employee_count": 12,
    "licensing": {"location": "other", "authority": "Jebel Ali Free Zone Authority"}
  }
}
```

`blueprint` is optional and takes the `PATCH /blueprint` fields; it is applied
in the same transaction only when a Company is created. Text must not have
surrounding whitespace or control characters (trim in the form).

Response `201` (created) or `200` (existing):

```json
{"outcome": "created", "company_id": "…", "membership_id": "…", "role": "company_admin"}
```

`role` is always `company_admin` for `created`. For `existing` it is the role
the person holds in that Company now: an operator may have demoted the founder
since. M1-10E fixed an answer that re-asserted `company_admin` there.

### `GET /me/companies`

`[{"company_id": "…", "name": "…", "membership_id": "…", "role": "company_admin"}]`,
ordered by name: the caller's active Memberships only. 403 for an identity
HeroOS does not know (or a suspended User / revoked binding).

### `GET /companies/{company_id}/membership`

`{"company_id", "membership_id", "role": "member" | "company_admin", "can_update_blueprint": bool}`.
For showing or hiding edit controls only; the API enforces the role.

### `GET /companies/{company_id}/blueprint` and `PATCH` (administrators)

```json
{
  "company_id": "…",
  "legal_name": "…", "industry": "…", "employee_count": 12,
  "licensing": {"location": "difc" | "other" | "not_sure" | null, "authority": "…" | null},
  "jurisdiction": {
    "readiness": "supported_confirmed" | "unconfirmed" | "unsupported",
    "reason": "confirmed" | "jurisdiction_not_supported" | "licensing_not_provided"
              | "licensing_not_sure" | "licensing_authority_missing"
              | "awaiting_confirmation" | "licensing_changed_since_confirmation",
    "employment_jurisdiction": "uae_federal" | "difc" | "adgm" | "other" | null,
    "confirmed_at": "…" | null,
    "guidance_allowed": false
  },
  "updated_at": "…" | null
}
```

`PATCH` accepts `legal_name`, `industry`, `employee_count` and `licensing`
(replaced as a whole; `null` clears). Only the fields sent change. Members get
403. `licensing.authority` is accepted only with `location: "other"`.

UI rules from the 13 October direction:

- First question: DIFC or Other (and "Not sure" if offered). For Other, the
  second selection uses JJ's licensing-authority list; until it exists, a
  free-text field (stored as text, never interpreted).
- Show `jurisdiction.reason` as an explanation; never present a jurisdiction
  the API did not return. For `unsupported`, explain that HeroOS V1 does not
  cover that jurisdiction.
- No jurisdiction quiz.

M1-10D follows these rules (offering "I'm not sure", with free text for Other).
See [Customer Onboarding and Workspace UI §6](../architecture/web-onboarding.md#6-jurisdiction-ui).
