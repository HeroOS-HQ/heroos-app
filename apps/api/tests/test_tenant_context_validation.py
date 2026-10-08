"""Tenant context input validation, which happens before any SQL is sent.

Behaviour against PostgreSQL (transaction-local scope, RLS, pooling) is proven in
``tests/tenant_isolation``.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.tenancy.context import TenantContextError, set_tenant_context


@pytest.fixture
def session() -> Iterator[tuple[Session, list[str]]]:
    engine = create_engine("sqlite+pysqlite://")
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(*args: Any) -> None:
        statements.append(args[2])

    with Session(engine) as db:
        yield db, statements
    engine.dispose()


@pytest.mark.parametrize(
    "company_id",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("not-a-uuid", id="malformed"),
        pytest.param("00000000-0000-0000-0000-000000000000", id="nil-string"),
        pytest.param(str(uuid.uuid4()), id="uuid-string"),
        pytest.param("' OR true; --", id="injection"),
        pytest.param(uuid.UUID(int=0), id="nil-uuid"),
        pytest.param(42, id="integer"),
    ],
)
def test_rejects_anything_but_a_non_nil_uuid_before_touching_the_database(
    session: tuple[Session, list[str]], company_id: Any
) -> None:
    db, statements = session

    with pytest.raises(TenantContextError):
        set_tenant_context(db, company_id)

    assert statements == []
