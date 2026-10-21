# Company Blueprint: the canonical company context (M2-NEW-03)

**Status:** Implemented (M2-NEW-03). Migration D5 (`671bbbfc74ae`), schema contract 8\
**Owner:** Technical Lead\
**Milestone:** [M2 — Reliable AI HR Workflow Platform](../milestones/m2-reliable-ai-hr-workflow-platform.md)\
**Related:** [Signed-in Workspace](signed-in-workspace.md), [Customer Onboarding](web-onboarding.md),
[ADR-010](../decisions/ADR-010-company-registration-and-administrators.md),
[Tenant Isolation](tenant-isolation.md), [Privacy decision register](../privacy/decision-register.md)

## 1. What it is

The Company Blueprint is the one place HeroOS keeps what it knows about a
company. It is not a settings page. With the confirmed jurisdiction, approved
Playbooks, the Conditions Library and authorized case history, it is one of
the trusted sources the HeroOS AI layer (M2-NEW-05) will use.

```text
ONBOARDING         creates the first, minimum Company + Blueprint answers
COMPANY BLUEPRINT  lets the company complete and maintain them (/workspaces/{id}/settings)
HEROOS AI          reads one server-side object: CompanyBlueprintContext
```

There is one model, one validation and one write path for both onboarding and
the Blueprint page. There is no second company-context store, no AI-specific
copy of any field, and no client-side storage standing in for one.

## 2. Where every field lives

Each field has exactly one writable source.

| Concept | Canonical source | Written by | API (`GET/PATCH /companies/{id}/blueprint`) | Onboarding | Blueprint page |
| --- | --- | --- | --- | --- | --- |
| Company display name | `companies.name` | Registration (`heroos_register_company`) | `company_name` (read only here) | Company name (required) | Shown, read only |
| Legal company name | `company_blueprints.legal_name` (≤ 200) | Administrators | `legal_name` | Optional | Edit |
| Industry | `company_blueprints.industry` (≤ 120) | Administrators | `industry` | Optional | Edit |
| Number of employees | `company_blueprints.employee_count` (0–10,000,000) | Administrators | `employee_count` | Optional | Edit |
| Company website | `company_blueprints.website_url` (≤ 500, normalized `http(s)`) | Administrators | `website_url` | Optional | Edit |
| Company summary | `company_blueprints.company_summary` (≤ 2,000, plain text, line breaks kept) | Administrators | `company_summary` | Optional | Edit |
| Licensing answer | `company_blueprints.licensing_location` (`difc`, `other`, `not_sure`) and `licensing_authority` (≤ 120, only with `other`) | Administrators | `licensing` | Required choice | Edit ("Jurisdiction") |
| Employment jurisdiction | `company_blueprints.employment_jurisdiction` + the licensing answer it was confirmed against + `jurisdiction_confirmed_at` | Platform operator only (`confirm-jurisdiction`); the API role holds no privilege | `jurisdiction` (readiness, reason, confirmed jurisdiction, `guidance_allowed`) | Never | Shown plainly, never as a "confirmed" badge |
| HR policies exist | `company_blueprints.policies_exist` (`yes`, `no`, `not_sure`; NULL = not answered) | Administrators | `policies_exist` | Optional | Edit |
| Policy details | `company_blueprints.policy_context` (≤ 1,000, plain text) | Administrators | `policy_context` | Not asked | Edit |
| HR support | `company_blueprints.hr_support` (`none`, `internal`, `external`, `mixed`, `other`) | Administrators | `hr_support` | Not asked | Edit |
| HR support notes | `company_blueprints.hr_support_notes` (≤ 500, plain text) | Administrators | `hr_support_notes` | Not asked | Edit |
| Primary contact | `company_blueprints.primary_contact_membership_id` → `memberships(company_id, id)` | The server at registration (the founder); administrators later | `primary_contact_membership_id` (write), `primary_contact` (read) | The founder, shown on Review | Edit (choose among people with access) |
| People with access | `memberships` (active) of `users` (active) | Identity operator / registration | `people` (read only) | — | Listed without names |
| Last updated | `company_blueprints.updated_at` | The database on every change (customer or operator) | `updated_at` | — | "Last updated 21 Oct 2026, 10:05 UTC" |
| Completeness | Derived (`app.companies.blueprint.missing_details`) | — | `completeness` | — | One quiet line + "needs attention" list |

`primary_jurisdiction` is the M1-04 placeholder: kept unchanged for old rows,
never shown, never part of the context.

### Company vs Blueprint ownership

The display name belongs to the Company (`companies.name`), which names the
workspace everywhere (discovery, switching, headers). The Blueprint never
copies it: the read model and the context *project* it. The Blueprint page
shows it read only; renaming a workspace is not part of M2-NEW-03.

## 3. Validation (shared by both write paths)

| Rule | API (authoritative) | Web (same rule, earlier feedback) | Database (backstop) |
| --- | --- | --- | --- |
| One-line text | `refuse_untidy_text` (no surrounding space, Python `isprintable`) | `checkText` | lengths |
| Multi-line text | `app.companies.blueprint.plain_text` (line breaks and tabs only) | `checkPlainText` (also tidies pasted CRLF, non-breaking and zero-width spaces before sending) | length and control-character CHECKs |
| Website | `normalize_website_url` | `normalizeWebsiteUrl` | `http://` / `https://` prefix, ≤ 500, no space or control character |
| Choices | `Literal[...]` | option lists | `ck_company_blueprints_policies_exist`, `ck_company_blueprints_hr_support` |
| Primary contact | an active Membership of an active User in this Company, checked in the write transaction | a choice among `people` | Company-qualified foreign key |

The website is normalized identically on both sides, proven by one shared
list of cases (`apps/api/tests/fixtures/website_urls.json`, run by the API and
the web tests):

- `http` or `https` only; `https://` is assumed when no scheme is typed;
- the scheme and host are lowercased, and a lone trailing `/` is dropped;
- refused: any other scheme (`javascript:`, `data:`, `file:`, `ftp:`,
  `mailto:`, …), credentials (`user@`), a port, an IP address or single-label
  host (`localhost`), spaces, control or non-ASCII characters, a backslash.

Founder registration takes `BlueprintFields` (every company answer) and the
administrator update takes `BlueprintUpdate` (the same, plus the primary
contact). Unknown fields are refused with 422 everywhere (`extra="forbid"`),
so the display name, people, completeness, the jurisdiction confirmation and
policy documents can never be written through the Blueprint. Refusals never
echo the submitted value.

## 4. People: primary contact, current user, multiple users

Three different things, never collapsed:

- **The company**: the Company row and its Blueprint.
- **The primary contact**: the main person HeroOS should know about, a
  Membership of the same Company. It can be someone other than the person
  using HeroOS.
- **The current user**: whoever made this request, from the authenticated
  Membership (`AuthenticatedCompanyContext`), never from client input.

HeroOS keeps no names or email addresses (users hold an id and a status only;
identity-provider subjects stay in `user_identities` and are never exposed).
So a person is their Membership: `membership_id`, `role`, `member_since`,
`is_current_user`, `is_primary_contact`. The Blueprint page tells people apart
by "You" and the date they joined, and shows no roles (the approved design).

Rules:

- At registration the server sets the founder's own Membership as the first
  primary contact. The request can't name one (422).
- An administrator can choose any *active* person with access. The API checks
  it in the write transaction and answers the same 422 for another Company's
  Membership, a revoked one or an id that exists nowhere (nothing about other
  Companies is disclosed). The Company-qualified foreign key
  (`company_id, primary_contact_membership_id → memberships(company_id, id)`)
  refuses another Company's Membership again, even for the database owner.
- If the chosen person later loses access (revoked Membership or suspended
  User), the reference is kept (nothing is deleted) but nobody is presented as
  the primary contact, and "Primary contact" needs attention again.
- Existing Companies start without a primary contact (NULL): the migration
  chooses nobody.

Multiple users: the model already supports many Memberships per Company, each
with its own identity and role. M2-NEW-03 adds no invitations, role editor,
member removal or team administration. Those, names and emails belong to
People & access (M2-NEW-10).

## 5. Jurisdiction authority

The jurisdiction stays exactly as M1-10C defined it:

- The customer deliberately answers where the business licence was issued
  (onboarding's **Jurisdiction** stage, the Blueprint's **Jurisdiction**
  section). The answer is information, never a legal conclusion.
- Only the platform operator's confirmation establishes an employment
  jurisdiction (`app.companies.jurisdiction`). Workflows read it through
  `company_jurisdiction` / `require_supported_jurisdiction`, unchanged.
- UAE Federal / MOHRE and DIFC stay separate. ADGM and anything else is
  unsupported. No AI, summary, website or policy text can infer, set or change
  a jurisdiction. If free text mentions a jurisdiction, the canonical fields
  remain authoritative (tested).
- The context carries the jurisdiction as the workflows see it (readiness,
  reason, confirmed jurisdiction, `guidance_allowed`) and the licensing answer
  separately. There is no AI-specific jurisdiction field.

Terminology: the user-facing label is "Jurisdiction". The question itself
stays "Where is your company licensed?", because that is what the answer
records.

## 6. Policies: existence and context, not documents

- **Implemented:** whether policies exist (`yes` / `no` / `not_sure` / not
  answered) and short policy details (for example "Employee handbook,
  disciplinary policy").
- **Deferred:** uploading or storing policy documents. Document retention is
  undecided ([PRIV-004](../privacy/decision-register.md), Legal Review
  Required), and no document domain exists. No public storage, temporary
  upload or file field exists. The page says "Uploading policy documents isn't
  available yet."

## 7. Website: stored only

`website_url` is an address the company gives. M2-NEW-03 adds no fetching,
crawling, scraping, search, browser automation, summarization or ingestion.
The page shows it as a link (`rel="noopener noreferrer nofollow"`) and says
"HeroOS keeps the address only. It doesn't visit or read your website." A
later controlled retrieval (JJ, 21 Oct: read only that page, nowhere else)
must be designed separately, with its own allow-list and request-forgery
controls. Refusing IP addresses, ports and credentials at storage time is
defence in depth for that future work, not a substitute for it.

## 8. `CompanyBlueprintContext` (the AI contract)

`app.companies.blueprint.load_company_blueprint_context(scope, context)` is the
only way HeroOS AI (M2-NEW-05) obtains company context. It returns frozen
dataclasses:

```python
CompanyBlueprintContext(
    company_id: UUID,
    company_display_name: str,          # companies.name
    legal_name: str | None,
    industry: str | None,
    employee_count: int | None,
    website_url: str | None,            # stored address only, never fetched
    company_summary: str | None,
    jurisdiction: JurisdictionContext(
        readiness: str,                 # supported_confirmed | unconfirmed | unsupported
        reason: str,
        employment_jurisdiction: str | None,   # only while the confirmation is current
        confirmed_at: datetime | None,
        guidance_allowed: bool,         # only for a supported, confirmed jurisdiction
        licensing_location: str | None, # the customer's statement
        licensing_authority: str | None,
    ),
    policies_exist: str | None,         # yes | no | not_sure | None
    policy_context: str | None,
    hr_support: str | None,             # none | internal | external | mixed | other | None
    hr_support_notes: str | None,
    primary_contact: CompanyPerson | None,
    current_user: CompanyPerson,
    updated_at: datetime | None,
    missing: tuple[str, ...],           # details that need attention
)  # .complete

CompanyPerson(membership_id, user_id, role, member_since, is_current_user, is_primary_contact)
```

It contains no password, token, session, identity-provider subject or issuer,
claims, binding id, email, audit or actor field, infrastructure detail or raw
row. `tests/companies/test_blueprint.py` pins the exact field set and refuses
any credential-like or identity-provider name. It is a domain object, not a
prompt: nothing here builds prompts, calls a model or interprets policy text.

The HTTP read model (`BlueprintOut`) is a projection of the same object plus
`people`, so the page and HeroOS AI can never read different meanings.

## 9. Completeness and "last updated"

`missing` lists, in page order: `legal_name`, `industry`, `employee_count`,
`company_summary`, `jurisdiction` (no answer, "not sure", or another
jurisdiction without its authority), `policies` (not answered or "not sure"),
`hr_support`, `primary_contact`. The website and the notes are optional and
never need attention. The page shows one quiet line ("Blueprint complete" or
"N details need attention") and a list of what needs attention, never a score
or a compliance claim. Onboarding's ready page says the Blueprint is
"Started: N details to complete", never complete because setup finished.

`updated_at` is the row's real update time (the ORM refreshes it on every
change; the operator sets it when confirming a jurisdiction). The page shows
the date and time in UTC.

## 10. Save notification

After a successful save the page shows "Company Blueprint updated" and the
fields saved ("HR support, HR support notes saved."), in a polite
`role="status"` region that takes focus and can be dismissed; saved rows are
marked "Updated". Nothing is sent to anyone: notifying the HeroOS team of
Blueprint changes (JJ, 21 Oct) needs a decided channel and retention
(PRIV-015) and is not built.

## 11. Persistence: migration D5 (`671bbbfc74ae`)

- Additive only: seven nullable columns on `company_blueprints`, their CHECKs
  (text checks in the migration only: they use PostgreSQL functions) and the
  Company-qualified foreign key. Nothing is backfilled; no row is created,
  changed or deleted; nobody repeats onboarding.
- Grants: the API role gets column-level `INSERT, UPDATE` on the new columns
  (it already reads the row under RLS). The identity operator gets nothing and
  still reads only licensing and confirmation columns. Guards in the migration
  verify both, and that the API role still can't write the confirmation.
- RLS: unchanged. The new columns live in an existing tenant table with the
  single `tenant_isolation` policy. No new table.
- `heroos_schema_contract()` = 8. The API needs at least 8; the operator CLI
  exactly 8. The M2-NEW-02 API (contract ≥ 7) keeps working on D5.
- Downgrade is refused once any new field holds a value: roll forward.

Deploy order: back up → D5 → API (and operator CLI) → web. The web app also
works against an API without D5 (it reads such a Blueprint as `legacy` and
edits only the profile and jurisdiction), because Vercel deploys `dev` before
Render is redeployed. A founder who fills the new onboarding fields during
that window gets a field error from the old API.

## 12. Not in M2-NEW-03

| Deferred | Where |
| --- | --- |
| Website retrieval of any kind | Later, separately designed |
| Policy document upload/storage | Blocked on PRIV-004 |
| Names, emails, invitations, role editing, member removal | M2-NEW-10 (People & access) |
| Renaming the workspace | Not requested |
| Notifying the HeroOS team of Blueprint updates | Needs a decision (PRIV-015) |
| Hannah on the Blueprint | JJ asset ("taking notes" pose); no new art or animation |
| Any LLM use of the context | M2-NEW-05 (reads `CompanyBlueprintContext` only) |

## 13. Tests

- API without a database: `tests/companies/test_blueprint.py` (URL cases,
  text rules, completeness, the exact context contract).
- API over SQLite: `tests/auth/test_company_blueprint_context_api.py` (GET,
  partial PATCH, unknown and read-only fields, limits, URL normalization and
  unsafe schemes, policies and HR support values, primary contact
  same-company success and cross-company refusal, current user vs contact,
  revoked contact, completeness, context = API view, cross-company 403).
- PostgreSQL: `tests/tenant_isolation/test_company_blueprint_context.py`
  (RLS scope, the foreign key even for the owner, database CHECKs, column
  privileges, the operator's lack of access, registration stores the context
  and the founder as contact, D5 additive and its rollback guard).
- Web: `lib/onboarding/model.test.ts` (the same URL cases, plain text, BFF
  parsing), `components/blueprint/blueprint-page.test.tsx`,
  `components/onboarding/onboarding-wizard.test.tsx`, `lib/server/*.test.ts`.
- End to end (`make e2e-check`): `browser` BP-1 to BP-4 (onboarding →
  Blueprint → edit → navigate away → reload → persisted; jurisdiction
  unchanged; primary contact kept; no other Company visible), `registration`
  R1-6b, `isolation` D-4b/D-4c, `migration` MIG-54 to MIG-59.
