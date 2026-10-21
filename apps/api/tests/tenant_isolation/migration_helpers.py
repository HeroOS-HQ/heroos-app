"""Shared steps for the migration-chain suites (B1a/B1b and C1).

The databases come from the ``legacy_db`` fixture (conftest): seeded at
``97d4200fe7a2`` exactly as a pre-M1-10B deployment would be, then migrated
with Alembic as an operator would. Three API generations are exercised as the
API runtime role:

- **371dd50** (pre-M1-10B): ``legacy_371dd50``.
- **169261d** (M1-10B): ``legacy_169261d``.
- **current** (M1-10C): the real application over HTTP.
"""

import uuid
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.development import (
    DEVELOPMENT_ISSUER,
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import TEST_DEV_SECRET
from tests.tenant_isolation import legacy_371dd50 as legacy
from tests.tenant_isolation import legacy_169261d as m110b
from tests.tenant_isolation.conftest import LegacyDatabase, run_alembic

PRE_B1 = "97d4200fe7a2"
B1A = "b8a11c15ed91"
B1B = "09cb5ec569b9"
C1 = "3f6c2a9d81b4"
D1 = "75ec6db8b6c1"
D2 = "e64497d997d8"
D3 = "8d217d768395"
D4 = "c4a7e2d9b310"
D5 = "671bbbfc74ae"
# The legacy users are bound under the development issuer, so the current API
# can be exercised end to end with development tokens.
LEGACY_ISSUER = DEVELOPMENT_ISSUER
REFERENCE = "HER-230"


def b1a(db: LegacyDatabase, *, issuer: str = LEGACY_ISSUER, count: str = "2") -> None:
    result = run_alembic(
        db.admin_url,
        "-x",
        f"legacy_identity_issuer={issuer}",
        "-x",
        f"legacy_identity_user_count={count}",
        "upgrade",
        B1A,
    )
    assert result.returncode == 0, result.stderr


def upgrade(db: LegacyDatabase, target: str) -> None:
    result = run_alembic(db.admin_url, "upgrade", target)
    assert result.returncode == 0, result.stderr


def b1b(db: LegacyDatabase) -> None:
    upgrade(db, B1B)


@contextmanager
def engine_for(url: str) -> Iterator[Engine]:
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def admin_scalar(db: LegacyDatabase, sql: str, **params: object) -> object:
    with engine_for(db.admin_url) as engine, engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def revision(db: LegacyDatabase) -> object:
    return admin_scalar(db, "SELECT version_num FROM alembic_version")


def operator_sql(
    db: LegacyDatabase, *statements: str, company: uuid.UUID | None = None, **params: Any
) -> None:
    """Plain SQL as the identity-operator login, attributed, in one transaction.

    Schema-independent on purpose: it is what any operator tooling (the M1-10B
    CLI included) sends for a lifecycle change.
    """
    with engine_for(db.operator_url) as engine, engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": REFERENCE}
        )
        if company is not None:
            conn.execute(
                text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(company)}
            )
        for statement in statements:
            conn.execute(text(statement), params)


# --- the three APIs ----------------------------------------------------------------


def old_api_authorizes(db: LegacyDatabase, subject: str, company: uuid.UUID) -> bool:
    """The 371dd50 authorization path as the API runtime role."""
    with engine_for(db.runtime_url) as engine, Session(engine) as session:
        try:
            user = legacy.resolve_user(
                session, legacy.VerifiedIdentity(subject=subject, issuer=LEGACY_ISSUER)
            )
            legacy.authorize_company(session, user, company)
        except legacy.AuthorizationError:
            return False
        return True


def m110b_api_status(db: LegacyDatabase, subject: str, company: uuid.UUID) -> int:
    """What the 169261d API answers for ``GET /companies/{company}`` and ``/cases``.

    200 when authorized and both reads succeed, 403 on an authorization denial.
    Any SQL error propagates (the API would answer 500).
    """
    with engine_for(db.runtime_url) as engine, Session(engine) as session:
        try:
            user = m110b.resolve_user(
                session, m110b.VerifiedIdentity(subject=subject, issuer=LEGACY_ISSUER)
            )
            context = m110b.authorize_company(session, user, company)
        except m110b.AuthorizationError:
            return 403
        assert m110b.get_company(session, context) is not None
        assert {case.company_id for case in m110b.list_cases(session, context)} <= {company}
        session.rollback()
        return 200


@contextmanager
def current_api(db: LegacyDatabase) -> Iterator[TestClient]:
    """The real current application over HTTP, as the API runtime role."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="development",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="development",
        heroos_dev_auth_secret=TEST_DEV_SECRET,
    )
    app = create_app(settings)
    provider = DevelopmentAuthenticationProvider(environment="development", secret=TEST_DEV_SECRET)
    with engine_for(db.runtime_url) as engine:
        sessions = sessionmaker(bind=engine, autoflush=False)

        def _db() -> Generator[Session, None, None]:
            with sessions() as session:
                yield session

        app.dependency_overrides[get_authentication_provider] = lambda: provider
        app.dependency_overrides[get_db] = _db
        yield TestClient(app)


def dev_headers(subject: str) -> dict[str, str]:
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject=subject
    )
    return {"Authorization": f"Bearer {token}"}


def current_api_status(client: TestClient, subject: str, company: uuid.UUID) -> int:
    response = client.get(f"/companies/{company}/cases", headers=dev_headers(subject))
    return response.status_code
