"""Tenant context never leaks through the SQLAlchemy connection pool.

The pool holds exactly one connection, so every session reuses the same
PostgreSQL backend (asserted with pg_backend_pid()). The raw
``heroos.company_id`` value is read straight from PostgreSQL at the start of
each checkout instead of being inferred.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import cases
from tests.tenant_isolation.conftest import (
    Tenant,
    TenantDatabase,
    Tenants,
    backend_pid,
    count_rows,
    scope_for,
    tenant_setting,
)


@pytest.fixture
def single_connection_engine(tenant_database: TenantDatabase) -> Iterator[Engine]:
    # Same pool settings as the API engine (app/db/session.py), limited to one
    # connection.
    engine = create_engine(
        tenant_database.runtime_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(single_connection_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=single_connection_engine, autoflush=False)


def _assert_fresh_checkout(db: Session, expected_pid: int | None) -> int:
    """No tenant value and no tenant rows on a newly checked-out connection."""
    pid = backend_pid(db)
    if expected_pid is not None:
        assert pid == expected_pid, "pool did not reuse the physical connection"
    assert tenant_setting(db) in (None, "")
    assert count_rows(db, "cases") == 0
    assert count_rows(db, "companies") == 0
    return pid


def _assert_sees_only(db: Session, tenant: Tenant) -> None:
    scope = scope_for(db, tenant)
    assert tenant_setting(db) == str(tenant.company)
    assert [c.id for c in cases.list_cases(scope)] == [tenant.case]
    # RLS alone, without the repository filter.
    assert set(db.scalars(text("SELECT company_id FROM cases"))) == {tenant.company}


def test_commit_clears_context_before_connection_reuse(
    sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with sessions() as db:
        pid = _assert_fresh_checkout(db, None)
        db.commit()
        _assert_sees_only(db, tenants.a)
        db.commit()

    with sessions() as db:
        _assert_fresh_checkout(db, pid)
        _assert_sees_only(db, tenants.b)
        db.commit()

    with sessions() as db:
        _assert_fresh_checkout(db, pid)


def test_rollback_clears_context_before_connection_reuse(
    sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with sessions() as db:
        pid = backend_pid(db)
        _assert_sees_only(db, tenants.a)
        db.rollback()
        assert tenant_setting(db) in (None, "")

    with sessions() as db:
        _assert_fresh_checkout(db, pid)
        _assert_sees_only(db, tenants.b)


def test_session_closed_mid_transaction_clears_context(
    sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # A request that ends without commit or explicit rollback (e.g. an exception
    # before the handler finishes): the pool's reset-on-return rolls back.
    db = sessions()
    pid = backend_pid(db)
    _assert_sees_only(db, tenants.a)
    db.close()

    with sessions() as db:
        _assert_fresh_checkout(db, pid)


def test_failed_statement_clears_context(sessions: sessionmaker[Session], tenants: Tenants) -> None:
    with sessions() as db:
        pid = backend_pid(db)
        _assert_sees_only(db, tenants.a)
        with pytest.raises(DBAPIError):
            db.execute(text("SELECT 1 / 0"))

    with sessions() as db:
        _assert_fresh_checkout(db, pid)


def test_alternating_companies_never_observe_each_other(
    sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    pid = None
    for i in range(20):
        tenant = tenants.a if i % 2 == 0 else tenants.b
        with sessions() as db:
            pid = _assert_fresh_checkout(db, pid)
            _assert_sees_only(db, tenant)
            if i % 3 == 0:
                db.rollback()
            else:
                db.commit()


def test_session_level_set_would_leak_which_is_why_it_is_forbidden(
    sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # Control: proves the checks above can detect a leak. A session-level
    # set_config(..., false) - equivalent to plain SET - survives commit and
    # pool return. Application code never does this.
    with sessions() as db:
        pid = backend_pid(db)
        db.execute(
            text("SELECT set_config('heroos.company_id', :value, false)"),
            {"value": str(tenants.a.company)},
        )
        db.commit()

    try:
        with sessions() as db:
            assert backend_pid(db) == pid
            assert tenant_setting(db) == str(tenants.a.company)
            assert count_rows(db, "cases") == 1
    finally:
        with sessions() as db:
            db.execute(text("RESET heroos.company_id"))
            db.commit()

    with sessions() as db:
        _assert_fresh_checkout(db, pid)
