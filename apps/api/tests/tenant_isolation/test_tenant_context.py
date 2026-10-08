"""Database tenant context: transaction-local, fail-closed when missing or invalid.

These tests use raw, unfiltered SQL as the runtime role, so anything returned is
what PostgreSQL RLS alone lets through.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import ObjectDeletedError

from app.repositories import cases
from app.tenancy.context import TenantContextError, get_tenant_context, set_tenant_context
from tests.tenant_isolation.conftest import (
    TENANT_TABLES,
    Tenants,
    count_rows,
    owners,
    scope_for,
)


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


# --- Missing context ---------------------------------------------------------


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_context_sees_no_tenant_rows(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    table: str,
) -> None:
    with admin_sessions() as admin:
        assert count_rows(admin, table) == 2

    with runtime_sessions() as db:
        assert get_tenant_context(db) is None
        assert count_rows(db, table) == 0


def test_users_are_global_identity_rows_not_tenant_rows(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # users has no company_id and no tenant policy: identity resolution needs it
    # before any Company is known. It holds only ids and identity subjects.
    with runtime_sessions() as db:
        assert count_rows(db, "users") == 3


def test_no_context_insert_is_rejected(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db, pytest.raises(DBAPIError) as exc_info:
        db.execute(
            text(
                "INSERT INTO cases (id, company_id, case_type, title) "
                "VALUES (gen_random_uuid(), :company, 'probation', 'no context')"
            ),
            {"company": tenants.a.company},
        )

    assert _sqlstate(exc_info.value) == "42501"
    assert "row-level security" in str(exc_info.value.orig)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE cases SET title = 'tampered'",
        "UPDATE companies SET name = 'tampered'",
        "UPDATE memberships SET user_id = user_id",
        "DELETE FROM cases",
        "DELETE FROM case_subjects",
        "DELETE FROM company_blueprints",
        "DELETE FROM memberships",
        "DELETE FROM companies",
    ],
)
def test_no_context_update_and_delete_affect_nothing(
    runtime_sessions: sessionmaker[Session],
    admin_sessions: sessionmaker[Session],
    tenants: Tenants,
    statement: str,
) -> None:
    with runtime_sessions() as db:
        assert db.execute(text(statement)).rowcount == 0  # type: ignore[attr-defined]
        db.commit()

    with admin_sessions() as admin:
        for table in TENANT_TABLES:
            assert count_rows(admin, table) == 2
        assert admin.scalar(text("SELECT count(*) FROM cases WHERE title = 'tampered'")) == 0


# --- Valid context -----------------------------------------------------------


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_context_exposes_only_that_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, table: str
) -> None:
    for tenant in (tenants.a, tenants.b):
        with runtime_sessions() as db:
            scope_for(db, tenant)
            assert owners(db, table) == {tenant.company}


def test_context_is_transaction_local(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        set_tenant_context(db, tenants.a.company)
        assert get_tenant_context(db) == tenants.a.company
        assert count_rows(db, "cases") == 1
        db.commit()

        assert get_tenant_context(db) is None
        assert count_rows(db, "cases") == 0

        set_tenant_context(db, tenants.a.company)
        assert count_rows(db, "cases") == 1
        db.rollback()

        assert get_tenant_context(db) is None
        assert count_rows(db, "cases") == 0


def test_plain_commit_drops_context_even_for_orm_refresh(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        case = cases.get_case(scope, tenants.a.case)
        assert case is not None
        db.commit()

        # The expired object is reloaded in a new, unscoped transaction.
        with pytest.raises(ObjectDeletedError):
            _ = case.title


def test_scope_commit_rebinds_the_same_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        scope = scope_for(db, tenants.a)
        case = cases.get_case(scope, tenants.a.case)
        assert case is not None
        scope.commit()

        assert get_tenant_context(db) == tenants.a.company
        assert case.title == "Case A"
        assert owners(db, "cases") == {tenants.a.company}


def test_transaction_cannot_switch_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        set_tenant_context(db, tenants.a.company)
        set_tenant_context(db, tenants.a.company)  # idempotent for the same Company

        with pytest.raises(TenantContextError):
            set_tenant_context(db, tenants.b.company)

        assert get_tenant_context(db) == tenants.a.company
        assert owners(db, "cases") == {tenants.a.company}


# --- Invalid context ---------------------------------------------------------


def test_nonexistent_company_context_sees_nothing_and_cannot_write(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    stale = uuid.uuid4()
    with runtime_sessions() as db:
        set_tenant_context(db, stale)
        for table in TENANT_TABLES:
            assert count_rows(db, table) == 0

        # Matches the policy, but the Company does not exist.
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) "
                    "VALUES (gen_random_uuid(), :company, 'probation', 'orphan')"
                ),
                {"company": stale},
            )
    assert _sqlstate(exc_info.value) == "23503"


@pytest.mark.parametrize("raw_value", ["", "not-a-uuid", "' OR true --", "*"])
def test_malformed_raw_setting_never_widens_visibility(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, raw_value: str
) -> None:
    # set_tenant_context never writes these; this proves the database side
    # still fails closed if something else did.
    with runtime_sessions() as db:
        db.execute(
            text("SELECT set_config('heroos.company_id', :value, true)"), {"value": raw_value}
        )
        try:
            visible = count_rows(db, "cases")
        except DBAPIError as exc:
            assert _sqlstate(exc) == "22P02"  # invalid_text_representation
        else:
            assert raw_value == ""
            assert visible == 0


def test_application_rejects_invalid_context_before_the_database(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        for invalid in (None, "not-a-uuid", str(tenants.a.company), uuid.UUID(int=0)):
            with pytest.raises(TenantContextError):
                set_tenant_context(db, invalid)  # type: ignore[arg-type]
        assert get_tenant_context(db) is None
        assert count_rows(db, "cases") == 0
