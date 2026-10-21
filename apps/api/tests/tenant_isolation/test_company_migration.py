"""Migration C1 (M1-10C) on databases with pre-existing data.

Each test migrates a disposable legacy database (``legacy_db``: two Companies,
alice in A, bob in B, a Blueprint with legacy values for A only) through
B1a and B1b exactly as the staged deployment would, then applies C1.

Compatibility matrix (M1-10C acceptance; deployment order B1a -> M1-10B API ->
B1b -> C1 -> current API):

    M1-10B API + C1 -> works      current API + B1b -> refuses to start
    current API + legacy data at head -> works  (test_identity_migration.py)
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity import companies, service
from app.identity.operator import set_actor_reference
from tests.tenant_isolation.conftest import LegacyDatabase, run_alembic
from tests.tenant_isolation.migration_helpers import (
    B1B,
    C1,
    LEGACY_ISSUER,
    REFERENCE,
    admin_scalar,
    b1a,
    b1b,
    current_api,
    dev_headers,
    engine_for,
    m110b_api_status,
    revision,
    upgrade,
)


def to_c1(db: LegacyDatabase) -> None:
    b1a(db)
    b1b(db)
    upgrade(db, C1)


def admin_rows(db: LegacyDatabase, sql: str, **params: object) -> list[tuple[Any, ...]]:
    with engine_for(db.admin_url) as engine, engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql), params)]


def test_c1_preserves_people_companies_and_blueprints_and_promotes_nobody(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    before = {
        table: admin_rows(legacy_db, f"SELECT row_to_json(t)::text FROM {table} t ORDER BY t.id")
        for table in ("companies", "users", "user_identities", "cases", "identity_events")
    }
    events_before = admin_scalar(legacy_db, "SELECT count(*) FROM membership_events")

    upgrade(legacy_db, C1)

    for table, rows in before.items():
        after = admin_rows(legacy_db, f"SELECT row_to_json(t)::text FROM {table} t ORDER BY t.id")
        assert after == rows, table
    # Every existing Membership is a member: the migration makes nobody an administrator.
    assert admin_rows(legacy_db, "SELECT id, status, role FROM memberships ORDER BY id") == sorted(
        [
            (legacy_db.alice_membership, "active", "member"),
            (legacy_db.bob_membership, "active", "member"),
        ]
    )
    # A's legacy Blueprint keeps its values and gains unanswered, unconfirmed fields;
    # B, which had none, gets one empty Blueprint.
    assert admin_rows(
        legacy_db,
        "SELECT company_id, id = :bpa, legal_name, primary_jurisdiction, industry, employee_count, "
        "licensing_location, licensing_authority, employment_jurisdiction, "
        "confirmed_licensing_location, confirmed_licensing_authority, jurisdiction_confirmed_at "
        "FROM company_blueprints ORDER BY legal_name NULLS LAST",
        bpa=legacy_db.blueprint_a,
    ) == [
        (legacy_db.company_a, True, "Legacy A LLC", "DIFC", "Retail", 12, *([None] * 6)),
        (legacy_db.company_b, False, None, None, None, None, *([None] * 6)),
    ]
    # The migration writes no audit events of its own.
    assert admin_scalar(legacy_db, "SELECT count(*) FROM membership_events") == events_before
    assert admin_scalar(legacy_db, "SELECT count(*) FROM company_events") == 0
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 3


def test_m110b_api_keeps_working_on_c1(legacy_db: LegacyDatabase) -> None:
    # C1 can be applied while the M1-10B API still serves.
    to_c1(legacy_db)

    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 200
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_b) == 200
    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_b) == 403
    assert m110b_api_status(legacy_db, "stranger", legacy_db.company_a) == 403


def test_current_api_sees_legacy_data_as_unconfirmed_member_data(
    legacy_db: LegacyDatabase,
) -> None:
    # Legacy data migrated through C1 and on to the current schema (the
    # current API refuses to start below contract 8, test_identity_migration):
    # nothing legacy becomes a confirmation or an administrator on the way.
    to_c1(legacy_db)
    upgrade(legacy_db, "head")

    with current_api(legacy_db) as client:
        base = f"/companies/{legacy_db.company_a}"
        alice = dev_headers("alice-subject")
        assert client.get(base, headers=alice).json() == {
            "id": str(legacy_db.company_a),
            "name": "Legacy A",
        }
        assert client.get(f"{base}/membership", headers=alice).json()["role"] == "member"
        blueprint = client.get(f"{base}/blueprint", headers=alice).json()
        assert blueprint["legal_name"] == "Legacy A LLC"
        # The legacy "DIFC" label establishes nothing.
        assert blueprint["jurisdiction"]["readiness"] == "unconfirmed"
        assert blueprint["jurisdiction"]["reason"] == "licensing_not_provided"
        assert blueprint["jurisdiction"]["guidance_allowed"] is False
        assert (
            client.patch(f"{base}/blueprint", headers=alice, json={"legal_name": "x"}).status_code
            == 403
        )
        assert client.get(f"/companies/{legacy_db.company_b}", headers=alice).status_code == 403


def test_c1_downgrade_without_any_history_restores_b1b(legacy_db: LegacyDatabase) -> None:
    to_c1(legacy_db)

    downgraded = run_alembic(legacy_db.admin_url, "downgrade", B1B)
    assert downgraded.returncode == 0, downgraded.stderr
    assert revision(legacy_db) == B1B
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 2
    assert admin_scalar(legacy_db, "SELECT to_regclass('public.company_events')") is None
    assert (
        admin_scalar(
            legacy_db,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name IN ('memberships', 'company_blueprints', 'membership_events') "
            "AND column_name IN ('role', 'licensing_location', 'employment_jurisdiction')",
        )
        == 0
    )
    # B1b privileges are back exactly.
    assert admin_rows(
        legacy_db,
        "SELECT has_table_privilege('heroos_app_runtime', 'companies', 'INSERT'), "
        "has_table_privilege('heroos_app_runtime', 'company_blueprints', 'UPDATE'), "
        "has_table_privilege('heroos_identity_operator', 'companies', 'INSERT'), "
        "has_any_column_privilege('heroos_identity_operator', 'company_blueprints', 'SELECT'), "
        "has_column_privilege('heroos_identity_operator', 'companies', 'id', 'SELECT')",
    ) == [(True, True, False, False, True)]
    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 200

    # Rolling forward again is clean: still one Blueprint per Company.
    upgrade(legacy_db, C1)
    assert admin_scalar(legacy_db, "SELECT count(*) FROM company_blueprints") == 2


def _register(db: LegacyDatabase) -> None:
    with engine_for(db.operator_url) as engine, Session(engine, autoflush=False) as session:
        set_actor_reference(session, REFERENCE)
        companies.register_company(
            session,
            company_id=uuid.uuid4(),
            name="Registered after C1",
            issuer=LEGACY_ISSUER,
            subject="new-admin-subject",
        )
        session.commit()


def _self_register(db: LegacyDatabase) -> None:
    # Founder self-registration through the API role's database capability.
    with engine_for(db.runtime_url) as engine, engine.begin() as conn:
        conn.execute(
            text("SELECT * FROM heroos_register_company(:i, 'founder-subject', 'Founder Ltd')"),
            {"i": LEGACY_ISSUER},
        )


def _promote(db: LegacyDatabase) -> None:
    with engine_for(db.operator_url) as engine, Session(engine, autoflush=False) as session:
        set_actor_reference(session, REFERENCE)
        service.set_membership_role(
            session,
            company_id=db.company_a,
            membership_id=db.alice_membership,
            role="company_admin",
        )
        session.commit()


def _promote_and_demote(db: LegacyDatabase) -> None:
    _promote(db)
    with engine_for(db.operator_url) as engine, Session(engine, autoflush=False) as session:
        set_actor_reference(session, REFERENCE)
        service.set_membership_role(
            session, company_id=db.company_a, membership_id=db.alice_membership, role="member"
        )
        session.commit()


def _answer(db: LegacyDatabase) -> None:
    with engine_for(db.runtime_url) as engine, engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(db.company_a)}
        )
        conn.execute(text("UPDATE company_blueprints SET licensing_location = 'not_sure'"))


def _revoke(db: LegacyDatabase) -> None:
    # Any audited Membership change after C1 records the role.
    with engine_for(db.operator_url) as engine, Session(engine, autoflush=False) as session:
        set_actor_reference(session, REFERENCE)
        service.revoke_membership(session, company_id=db.company_b, membership_id=db.bob_membership)
        session.commit()


@pytest.mark.parametrize(
    "history",
    [
        pytest.param(_register, id="operator-registration"),
        pytest.param(_self_register, id="founder-self-registration"),
        pytest.param(_promote, id="administrator"),
        pytest.param(_promote_and_demote, id="role-change-undone"),
        pytest.param(_answer, id="licensing-answer"),
        pytest.param(_revoke, id="membership-change"),
    ],
)
def test_c1_downgrade_refuses_once_history_exists(legacy_db: LegacyDatabase, history: Any) -> None:
    to_c1(legacy_db)
    history(legacy_db)

    refused = run_alembic(legacy_db.admin_url, "downgrade", B1B)

    assert refused.returncode != 0
    assert "roll forward" in refused.stderr
    assert revision(legacy_db) == C1
    assert admin_scalar(legacy_db, "SELECT heroos_schema_contract()") == 3
