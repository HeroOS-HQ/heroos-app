"""The Company Blueprint context on PostgreSQL (M2-NEW-03, migration D5).

As the RLS-restricted runtime role (Company repositories and the canonical
loader), the identity operator and the migration owner:

- the context is written and read only inside the Company's own tenant scope;
- the primary contact is a Membership of the same Company: the application
  refuses anything else, and the Company-qualified foreign key refuses it
  again, even for the owner;
- the database's own checks refuse unsafe websites and malformed text, even
  when the application is bypassed;
- the operator gets nothing new (it never reads the business context);
- founder registration stores the onboarding answers through the same path
  and makes the founder the primary contact;
- D5 is additive: existing data is untouched, and a rollback is refused once
  any new field holds a value.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.companies.blueprint import (
    InvalidPrimaryContact,
    load_company_blueprint,
    load_company_blueprint_context,
    save_blueprint_changes,
)
from tests.tenant_isolation.conftest import (
    LegacyDatabase,
    Tenant,
    Tenants,
    attribute_changes,
    run_alembic,
    scope_for,
)
from tests.tenant_isolation.migration_helpers import (
    D4,
    D5,
    admin_scalar,
    b1a,
    engine_for,
    upgrade,
)
from tests.tenant_isolation.test_founder_registration import (  # noqa: F401 (fixtures)
    URL,
    auth,
    client,
    http_sessions,
    rows,
    signing_key,
)

SUMMARY = "Two shops in Dubai.\n\nA store manager leads eight staff.\tPart-time cover too."
CONTEXT = {
    "website_url": "https://alpha.example",
    "company_summary": SUMMARY,
    "policies_exist": "yes",
    "policy_context": "Employee handbook",
    "hr_support": "external",
    "hr_support_notes": "A consultant helps.",
}
NEW_COLUMNS = (*CONTEXT, "primary_contact_membership_id")


def save(runtime_engine: Engine, tenant: Tenant, changes: dict[str, Any]) -> None:
    with Session(runtime_engine, autoflush=False) as session:
        save_blueprint_changes(scope_for(session, tenant), changes)
        session.commit()


def add_member(admin_engine: Engine, tenant: Tenant) -> uuid.UUID:
    """A second (active) person in ``tenant``'s Company; returns the Membership id."""
    with Session(admin_engine) as session:
        attribute_changes(session)
        user = session.scalar(
            text("INSERT INTO users (id) VALUES (gen_random_uuid()) RETURNING id")
        )
        membership = session.scalar(
            text(
                "INSERT INTO memberships (id, company_id, user_id) "
                "VALUES (gen_random_uuid(), :c, :u) RETURNING id"
            ),
            {"c": tenant.company, "u": user},
        )
        session.commit()
    assert isinstance(membership, uuid.UUID)
    return membership


def test_the_context_is_written_and_read_only_in_the_companys_own_scope(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    save(
        runtime_engine,
        tenants.a,
        {**CONTEXT, "primary_contact_membership_id": tenants.a.membership},
    )

    # One Company per transaction: the tenancy guard refuses a second one.
    with Session(runtime_engine) as session:
        view = load_company_blueprint(scope_for(session, tenants.a), tenants.a.context)
    with Session(runtime_engine) as session:
        other = load_company_blueprint(scope_for(session, tenants.b), tenants.b.context)
    context = view.context
    assert (context.website_url, context.company_summary) == ("https://alpha.example", SUMMARY)
    assert (context.policies_exist, context.hr_support) == ("yes", "external")
    assert context.primary_contact is not None
    assert context.primary_contact.membership_id == tenants.a.membership
    assert context.current_user.membership_id == tenants.a.membership
    assert [person.membership_id for person in view.people] == [tenants.a.membership]
    assert context.company_display_name == "Company A"
    assert context.updated_at is not None
    # Company B sees its own, untouched Blueprint and none of A's people.
    assert other.context.website_url is None and other.context.primary_contact is None
    assert [person.membership_id for person in other.people] == [tenants.b.membership]
    # Ground truth: only A's row changed, exactly as sent.
    assert rows(
        admin_engine,
        "SELECT company_id, website_url, company_summary, primary_contact_membership_id "
        "FROM company_blueprints ORDER BY legal_name",
    ) == [
        (tenants.a.company, "https://alpha.example", SUMMARY, tenants.a.membership),
        (tenants.b.company, None, None, None),
    ]


def test_without_a_tenant_context_the_runtime_role_sees_no_context(
    runtime_engine: Engine, tenants: Tenants
) -> None:
    save(runtime_engine, tenants.a, CONTEXT)
    with runtime_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM company_blueprints")) == 0
        assert conn.scalar(text("SELECT count(website_url) FROM company_blueprints")) == 0


def test_another_companys_membership_is_refused_by_the_application(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    for candidate in (tenants.b.membership, uuid.uuid4(), tenants.a.user):
        with (
            Session(runtime_engine, autoflush=False) as session,
            pytest.raises(InvalidPrimaryContact),
        ):
            save_blueprint_changes(
                scope_for(session, tenants.a),
                {"primary_contact_membership_id": candidate, "industry": "Taken"},
            )
    assert rows(
        admin_engine,
        "SELECT industry, primary_contact_membership_id FROM company_blueprints "
        "WHERE company_id = :c",
        c=tenants.a.company,
    ) == [(None, None)]


@pytest.mark.parametrize("as_owner", [False, True], ids=["runtime", "owner"])
def test_the_database_refuses_another_companys_membership_even_for_the_owner(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants, as_owner: bool
) -> None:
    engine = admin_engine if as_owner else runtime_engine
    with Session(engine) as session:
        scope_for(session, tenants.a)
        with pytest.raises(IntegrityError) as refused:
            session.execute(
                text(
                    "UPDATE company_blueprints SET primary_contact_membership_id = :m "
                    "WHERE company_id = :c"
                ),
                {"m": tenants.b.membership, "c": tenants.a.company},
            )
    assert getattr(refused.value.orig, "sqlstate", None) == "23503"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("website_url", "'javascript:alert(1)'", id="javascript-url"),
        pytest.param("website_url", "'ftp://alpha.example'", id="ftp-url"),
        pytest.param("website_url", "'alpha.example'", id="url-without-scheme"),
        pytest.param("website_url", "'https://alpha example'", id="url-with-space"),
        pytest.param("website_url", "'https://alpha.example/' || chr(10)", id="url-line-break"),
        pytest.param("website_url", "'https://a.example/' || repeat('x', 490)", id="long-url"),
        pytest.param("company_summary", "''", id="empty-summary"),
        pytest.param("company_summary", "'bell' || chr(7)", id="control-summary"),
        pytest.param("company_summary", "repeat('x', 2001)", id="long-summary"),
        pytest.param("policy_context", "repeat('x', 1001)", id="long-policy-context"),
        pytest.param("hr_support_notes", "repeat('x', 501)", id="long-hr-notes"),
        pytest.param("hr_support_notes", "'escape' || chr(27)", id="control-hr-notes"),
        pytest.param("policies_exist", "'maybe'", id="unknown-policies-answer"),
        pytest.param("hr_support", "'outsourced'", id="unknown-hr-support"),
    ],
)
def test_the_database_refuses_unsafe_or_malformed_context(
    admin_engine: Engine, tenants: Tenants, column: str, value: str
) -> None:
    with Session(admin_engine) as session, pytest.raises(DBAPIError) as refused:
        session.execute(
            text(f"UPDATE company_blueprints SET {column} = {value} WHERE company_id = :c"),
            {"c": tenants.a.company},
        )
    # A CHECK violation, or (the website) the column's own length limit.
    assert getattr(refused.value.orig, "sqlstate", None) in {"23514", "22001"}


def test_the_database_accepts_the_longest_valid_context(
    admin_engine: Engine, tenants: Tenants
) -> None:
    with Session(admin_engine) as session:
        session.execute(
            text(
                "UPDATE company_blueprints SET "
                "website_url = 'https://a.example/' || repeat('x', 482), "
                "company_summary = repeat('s', 1990) || chr(10) || chr(9) || repeat('t', 8), "
                "policy_context = repeat('p', 1000), hr_support_notes = repeat('h', 500), "
                "policies_exist = 'not_sure', hr_support = 'mixed' WHERE company_id = :c"
            ),
            {"c": tenants.a.company},
        )
        session.commit()
    assert rows(
        admin_engine,
        "SELECT char_length(website_url), char_length(company_summary) FROM company_blueprints "
        "WHERE company_id = :c",
        c=tenants.a.company,
    ) == [(500, 2000)]


def test_privileges_on_the_new_columns_are_exactly_the_api_roles(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        for column in NEW_COLUMNS:
            for privilege in ("SELECT", "INSERT", "UPDATE"):
                assert conn.scalar(
                    text(
                        "SELECT has_column_privilege('heroos_app_runtime', "
                        "'public.company_blueprints', :c, :p)"
                    ),
                    {"c": column, "p": privilege},
                ), (column, privilege)
                assert not conn.scalar(
                    text(
                        "SELECT has_column_privilege('heroos_identity_operator', "
                        "'public.company_blueprints', :c, :p)"
                    ),
                    {"c": column, "p": privilege},
                ), (column, privilege)
        # The jurisdiction confirmation is still out of the API role's reach.
        assert not conn.scalar(
            text(
                "SELECT has_column_privilege('heroos_app_runtime', "
                "'public.company_blueprints', 'employment_jurisdiction', 'UPDATE')"
            )
        )
        # Head: D7 (chat-first Case) on top of D6 (M2-NEW-07) and D5.
        assert conn.scalar(text("SELECT heroos_schema_contract()")) == 10


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT website_url FROM company_blueprints",
        "SELECT company_summary FROM company_blueprints",
        "SELECT primary_contact_membership_id FROM company_blueprints",
        "UPDATE company_blueprints SET hr_support = 'none'",
    ],
)
def test_the_operator_never_reads_or_writes_the_business_context(
    operator_engine: Engine, tenants: Tenants, sql: str
) -> None:
    with operator_engine.connect() as conn, pytest.raises(ProgrammingError) as refused:
        conn.execute(text(sql))
    assert getattr(refused.value.orig, "sqlstate", None) == "42501"


def test_a_revoked_primary_contact_is_no_longer_presented(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    colleague = add_member(admin_engine, tenants.a)
    save(runtime_engine, tenants.a, {"primary_contact_membership_id": colleague})
    with Session(runtime_engine) as session:
        context = load_company_blueprint_context(scope_for(session, tenants.a), tenants.a.context)
    assert context.primary_contact is not None
    assert context.primary_contact.membership_id == colleague
    assert not context.primary_contact.is_current_user
    assert context.current_user.membership_id == tenants.a.membership

    with Session(admin_engine) as session:
        attribute_changes(session)
        session.execute(
            text("UPDATE memberships SET status = 'revoked', revoked_at = now() WHERE id = :m"),
            {"m": colleague},
        )
        session.commit()
    with Session(runtime_engine) as session:
        context = load_company_blueprint_context(scope_for(session, tenants.a), tenants.a.context)
    # The reference stays (nothing is deleted), but nobody revoked is presented as the contact.
    assert context.primary_contact is None
    assert "primary_contact" in context.missing
    with Session(runtime_engine, autoflush=False) as session, pytest.raises(InvalidPrimaryContact):
        save_blueprint_changes(
            scope_for(session, tenants.a), {"primary_contact_membership_id": colleague}
        )


def test_registration_stores_the_onboarding_context_and_the_founder_as_primary_contact(
    client: TestClient,  # noqa: F811
    admin_engine: Engine,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    founder = auth("context-founder-subject")
    response = client.post(
        URL,
        headers=founder,
        json={
            "company_name": "[SYNTHETIC] Context Founder Co.",
            "blueprint": {
                "legal_name": "Context Founder LLC",
                "industry": "Hospitality",
                "employee_count": 9,
                "website_url": "Context-Founder.example/",
                "company_summary": SUMMARY,
                "policies_exist": "no",
                "licensing": {"location": "difc"},
            },
        },
    )
    assert response.status_code == 201
    company, membership = response.json()["company_id"], response.json()["membership_id"]
    assert rows(
        admin_engine,
        "SELECT website_url, company_summary, policies_exist, hr_support, "
        "primary_contact_membership_id::text FROM company_blueprints WHERE company_id = :c",
        c=company,
    ) == [("https://context-founder.example", SUMMARY, "no", None, membership)]

    blueprint = client.get(f"/companies/{company}/blueprint", headers=founder).json()
    assert blueprint["company_name"] == "[SYNTHETIC] Context Founder Co."
    assert blueprint["primary_contact"]["membership_id"] == membership
    assert blueprint["primary_contact"]["is_current_user"] is True
    assert blueprint["primary_contact"]["role"] == "company_admin"
    assert blueprint["jurisdiction"]["guidance_allowed"] is False
    assert blueprint["completeness"]["missing"] == ["hr_support"]
    # Editing later from the Blueprint goes through the same rules.
    edited = client.patch(
        f"/companies/{company}/blueprint",
        headers=founder,
        json={"hr_support": "none", "company_summary": "Now three shops."},
    ).json()
    assert (edited["hr_support"], edited["company_summary"]) == ("none", "Now three shops.")
    assert edited["completeness"] == {"complete": True, "missing": []}
    # Another Company's Membership is never accepted as the contact.
    stolen = client.patch(
        f"/companies/{company}/blueprint",
        headers=founder,
        json={"primary_contact_membership_id": str(tenants.a.membership)},
    )
    assert stolen.status_code == 422
    assert client.get(f"/companies/{tenants.a.company}/blueprint", headers=founder).status_code == (
        403
    )


def test_registration_never_takes_the_primary_contact_from_the_request(
    client: TestClient,  # noqa: F811
    admin_engine: Engine,
    tenants: Tenants,
    auth: Any,  # noqa: F811
) -> None:
    # The founder is the first primary contact, set by the server: a request
    # naming one (here another Company's Membership) is refused and creates nothing.
    before = rows(admin_engine, "SELECT count(*) FROM companies")
    response = client.post(
        URL,
        headers=auth("greedy-founder-subject"),
        json={
            "company_name": "Greedy Co.",
            "blueprint": {
                "primary_contact_membership_id": str(tenants.a.membership),
                "licensing": {"location": "difc"},
            },
        },
    )
    assert response.status_code == 422
    assert {error["type"] for error in response.json()["detail"]} == {"extra_forbidden"}
    assert rows(admin_engine, "SELECT count(*) FROM companies") == before


# --- the migration ------------------------------------------------------------------


def test_d5_is_additive_and_rolls_back_only_while_unused(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    upgrade(legacy_db, D4)
    snapshot = {
        table: admin_scalar(
            legacy_db,
            f"SELECT coalesce(json_agg(t ORDER BY t.id)::text, '') FROM {table} t",
        )
        for table in ("companies", "users", "memberships", "cases", "user_identities")
    }
    blueprints = admin_scalar(
        legacy_db,
        "SELECT json_agg(json_build_array(id, company_id, legal_name, industry, employee_count, "
        "licensing_location, employment_jurisdiction, updated_at) ORDER BY id)::text "
        "FROM company_blueprints",
    )

    upgrade(legacy_db, D5)
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 8
    for table, before in snapshot.items():
        after = admin_scalar(
            legacy_db,
            f"SELECT coalesce(json_agg(t ORDER BY t.id)::text, '') FROM {table} t",
        )
        assert after == before, table
    assert (
        admin_scalar(
            legacy_db,
            "SELECT json_agg(json_build_array(id, company_id, legal_name, industry, "
            "employee_count, licensing_location, employment_jurisdiction, updated_at) "
            "ORDER BY id)::text FROM company_blueprints",
        )
        == blueprints
    )
    # Every existing Blueprint starts with the new fields unanswered: nobody repeats onboarding.
    answered = " OR ".join(f"{column} IS NOT NULL" for column in NEW_COLUMNS)
    assert admin_scalar(legacy_db, f"SELECT count(*) FROM company_blueprints WHERE {answered}") == 0

    # Unused: reversible to D4 (contract 7), then re-applied.
    down = run_alembic(legacy_db.admin_url, "downgrade", D4)
    assert down.returncode == 0, down.stderr
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 7
    assert (
        admin_scalar(
            legacy_db,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'company_blueprints' AND column_name = 'website_url'",
        )
        == 0
    )
    upgrade(legacy_db, D5)
    with pytest.raises(DBAPIError):
        # The owner can't store an unsafe URL either.
        admin_scalar(
            legacy_db,
            "UPDATE company_blueprints SET website_url = 'javascript:x' RETURNING website_url",
        )
    with engine_for(legacy_db.admin_url) as engine, engine.begin() as conn:
        conn.execute(
            text("UPDATE company_blueprints SET hr_support = 'none' WHERE company_id = :c"),
            {"c": legacy_db.company_a},
        )
    refused = run_alembic(legacy_db.admin_url, "downgrade", D4)
    assert refused.returncode != 0
    assert "roll forward instead" in refused.stderr
    assert admin_scalar(legacy_db, "SELECT version_num FROM alembic_version") == D5
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 8
