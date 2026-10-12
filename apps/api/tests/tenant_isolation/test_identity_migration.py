"""Migrations B1a/B1b: backfill contract, API compatibility and rollback safety.

Every test gets its own disposable ``*_tenant_isolation_test`` database seeded
with legacy data at ``97d4200fe7a2`` (two Companies, alice and bob), then
migrates it with Alembic exactly as an operator would.

- **Old API**: the frozen ``371dd50`` authorization code (``legacy_371dd50``),
  running as the API runtime role.
- **New API**: the real application (``create_app``) over HTTP, authenticated by
  the development provider, running as the API runtime role.

Compatibility matrix (M1-10B acceptance):

    old API + B1a -> works        new API + B1a -> works
    old API + B1b -> fails closed new API + B1b -> works
"""

import uuid
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.exceptions import AuthorizationError
from app.auth.models import VerifiedIdentity
from app.auth.providers.development import (
    DEVELOPMENT_ISSUER,
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.auth.service import authorize_company, resolve_user
from app.core.config import Settings
from app.db.runtime_role import (
    API_MINIMUM_SCHEMA_CONTRACT,
    IncompatibleSchemaError,
    verify_runtime_role,
)
from app.db.session import get_db
from app.identity import service
from app.identity.operator import set_actor_reference
from app.main import create_app
from tests.auth.conftest import TEST_DEV_SECRET
from tests.tenant_isolation import legacy_371dd50 as legacy
from tests.tenant_isolation.conftest import TenantDatabase, disposable_database, run_alembic

PRE_B1 = "97d4200fe7a2"
B1A = "b8a11c15ed91"
B1B = "09cb5ec569b9"
# The legacy users are bound under the development issuer, so the new API can
# be exercised end to end with development tokens.
LEGACY_ISSUER = DEVELOPMENT_ISSUER
REFERENCE = "HER-230"


@dataclass(frozen=True)
class LegacyDatabase:
    admin_url: str
    runtime_url: str
    operator_url: str
    company_a: uuid.UUID
    company_b: uuid.UUID
    alice: uuid.UUID
    bob: uuid.UUID
    alice_membership: uuid.UUID
    bob_membership: uuid.UUID


def _as(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def legacy_db(tenant_database: TenantDatabase) -> Iterator[LegacyDatabase]:
    with disposable_database(tenant_database, "b1") as admin_url:
        migrated = run_alembic(admin_url, "upgrade", PRE_B1)
        assert migrated.returncode == 0, migrated.stderr
        ids = {name: uuid.uuid4() for name in ("a", "b", "alice", "bob", "ma", "mb")}
        engine = create_engine(admin_url)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO companies (id, name) VALUES (:a, 'Legacy A'), (:b, 'Legacy B')"),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, identity_subject) "
                    "VALUES (:alice, 'alice-subject'), (:bob, 'bob-subject')"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO memberships (id, company_id, user_id) "
                    "VALUES (:ma, :a, :alice), (:mb, :b, :bob)"
                ),
                ids,
            )
            conn.execute(
                text(
                    "INSERT INTO cases (id, company_id, case_type, title) "
                    "VALUES (gen_random_uuid(), :a, 'probation', 'Case A'), "
                    "(gen_random_uuid(), :b, 'probation', 'Case B')"
                ),
                ids,
            )
        engine.dispose()
        database = make_url(admin_url).database or ""
        yield LegacyDatabase(
            admin_url=admin_url,
            runtime_url=_as(tenant_database.runtime_url, database),
            operator_url=_as(tenant_database.operator_url, database),
            company_a=ids["a"],
            company_b=ids["b"],
            alice=ids["alice"],
            bob=ids["bob"],
            alice_membership=ids["ma"],
            bob_membership=ids["mb"],
        )


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


def b1b(db: LegacyDatabase) -> None:
    result = run_alembic(db.admin_url, "upgrade", B1B)
    assert result.returncode == 0, result.stderr


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


# --- the two APIs ----------------------------------------------------------------


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


@contextmanager
def new_api(db: LegacyDatabase) -> Iterator[TestClient]:
    """The real new application over HTTP, as the API runtime role."""
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


def new_api_status(client: TestClient, subject: str, company: uuid.UUID) -> int:
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject=subject
    )
    response = client.get(
        f"/companies/{company}/cases", headers={"Authorization": f"Bearer {token}"}
    )
    return response.status_code


@contextmanager
def operator_session(db: LegacyDatabase) -> Iterator[Session]:
    """An identity-operator session with the change reference set; commits on exit."""
    with engine_for(db.operator_url) as engine, Session(engine, autoflush=False) as session:
        set_actor_reference(session, REFERENCE)
        yield session
        session.commit()


# --- B1a backfill contract -------------------------------------------------------


def test_b1a_refuses_existing_users_without_backfill_arguments(legacy_db: LegacyDatabase) -> None:
    result = run_alembic(legacy_db.admin_url, "upgrade", B1A)

    assert result.returncode != 0
    assert "heroos migration refused" in result.stderr
    assert "legacy_identity_issuer" in result.stderr
    # Atomic: nothing of B1a exists, the legacy data is untouched.
    assert revision(legacy_db) == PRE_B1
    assert admin_scalar(legacy_db, "SELECT to_regclass('public.user_identities')") is None
    assert admin_scalar(legacy_db, "SELECT count(*) FROM users") == 2
    assert old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(
            ["-x", f"legacy_identity_issuer={LEGACY_ISSUER}"], "or neither", id="issuer-only"
        ),
        pytest.param(["-x", "legacy_identity_user_count=2"], "or neither", id="count-only"),
        pytest.param(
            ["-x", "legacy_identity_issuer=http://idp.test/", "-x", "legacy_identity_user_count=2"],
            "exact https issuer",
            id="plain-http",
        ),
        pytest.param(
            [
                "-x",
                "legacy_identity_issuer=https://idp.test/?tenant=x",
                "-x",
                "legacy_identity_user_count=2",
            ],
            "exact https issuer",
            id="query",
        ),
        pytest.param(
            [
                "-x",
                "legacy_identity_issuer=https://idp.test/' OR '1'='1",
                "-x",
                "legacy_identity_user_count=2",
            ],
            "exact https issuer",
            id="quote-injection",
        ),
        pytest.param(
            ["-x", f"legacy_identity_issuer={LEGACY_ISSUER}", "-x", "legacy_identity_user_count=3"],
            "does not match the existing users",
            id="wrong-count",
        ),
        pytest.param(
            ["-x", f"legacy_identity_issuer={LEGACY_ISSUER}", "-x", "legacy_identity_user_count=x"],
            "positive integer",
            id="non-numeric-count",
        ),
    ],
)
def test_b1a_refuses_missing_or_ambiguous_backfill_arguments_atomically(
    legacy_db: LegacyDatabase, arguments: list[str], expected: str
) -> None:
    result = run_alembic(legacy_db.admin_url, *arguments, "upgrade", B1A)

    assert result.returncode != 0
    assert expected in result.stderr
    assert revision(legacy_db) == PRE_B1
    assert admin_scalar(legacy_db, "SELECT to_regclass('public.user_identities')") is None


def test_b1a_refuses_backfill_arguments_on_an_empty_database(
    tenant_database: TenantDatabase,
) -> None:
    with disposable_database(tenant_database, "b1empty") as admin_url:
        assert run_alembic(admin_url, "upgrade", PRE_B1).returncode == 0
        result = run_alembic(
            admin_url,
            "-x",
            f"legacy_identity_issuer={LEGACY_ISSUER}",
            "-x",
            "legacy_identity_user_count=2",
            "upgrade",
            B1A,
        )
        assert result.returncode != 0
        assert "does not match the existing users" in result.stderr
        # Without arguments an empty database migrates normally.
        assert run_alembic(admin_url, "upgrade", "head").returncode == 0


def test_b1a_backfill_preserves_users_and_binds_the_exact_issuer(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)

    with engine_for(legacy_db.admin_url) as engine, engine.connect() as conn:
        bindings = conn.execute(
            text("SELECT user_id, issuer, subject, status FROM user_identities ORDER BY subject")
        ).all()
        events = conn.execute(
            text(
                "SELECT event_type, user_id, identity_id IS NOT NULL, actor_kind, db_role, "
                "actor_reference FROM identity_events ORDER BY user_id"
            )
        ).all()
        event_columns = set(
            conn.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name IN ('identity_events', 'membership_events')"
                )
            )
        )
        admin_login = conn.scalar(text("SELECT session_user"))

    # Stable internal IDs; one exact binding per legacy User.
    assert bindings == [
        (legacy_db.alice, LEGACY_ISSUER, "alice-subject", "active"),
        (legacy_db.bob, LEGACY_ISSUER, "bob-subject", "active"),
    ]
    assert sorted(events) == sorted(
        ("identity_bound", user, True, "owner", admin_login, f"alembic:{B1A}")
        for user in (legacy_db.alice, legacy_db.bob)
    )
    # Audit events never copy the external identity.
    assert not event_columns & {"issuer", "subject", "identity_subject"}


# --- API compatibility matrix ------------------------------------------------------


def test_old_api_keeps_working_on_b1a(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)

    assert old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)
    assert old_api_authorizes(legacy_db, "bob-subject", legacy_db.company_b)
    assert not old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_b)


def test_new_api_works_on_b1a(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)

    with new_api(legacy_db) as client:
        assert new_api_status(client, "alice-subject", legacy_db.company_a) == 200
        assert new_api_status(client, "bob-subject", legacy_db.company_b) == 200
        assert new_api_status(client, "alice-subject", legacy_db.company_b) == 403
        assert new_api_status(client, "stranger", legacy_db.company_a) == 403


def test_new_api_works_on_b1b(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)

    with new_api(legacy_db) as client:
        assert new_api_status(client, "alice-subject", legacy_db.company_a) == 200
        assert new_api_status(client, "bob-subject", legacy_db.company_b) == 200
        assert new_api_status(client, "bob-subject", legacy_db.company_a) == 403


def test_old_api_fails_closed_on_b1b(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)

    # The old ORM mapping selects users.identity_subject, which no longer exists:
    # every protected request errors (HTTP 500 at the error boundary) and no
    # Company context is ever produced.
    with pytest.raises(ProgrammingError) as exc_info:
        old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42703"


def test_new_api_requires_the_identity_schema_contract(legacy_db: LegacyDatabase) -> None:
    with engine_for(legacy_db.runtime_url) as engine:
        # Pre-B1a schema: the new API refuses to start rather than fail per request.
        with pytest.raises(IncompatibleSchemaError):
            verify_runtime_role(engine)
        b1a(legacy_db)
        verify_runtime_role(engine)
        b1b(legacy_db)
        verify_runtime_role(engine)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT heroos_schema_contract()")) == 2
    assert API_MINIMUM_SCHEMA_CONTRACT == 1


# --- revocation and rollback --------------------------------------------------------


def test_revoked_access_stays_denied_through_the_supported_recovery_procedure(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    with operator_session(legacy_db) as session:
        service.revoke_membership(
            session, company_id=legacy_db.company_b, membership_id=legacy_db.bob_membership
        )
        service.suspend_user(session, user_id=legacy_db.alice)

    # New API: both denied on the next request.
    with new_api(legacy_db) as client:
        assert new_api_status(client, "alice-subject", legacy_db.company_a) == 403
        assert new_api_status(client, "bob-subject", legacy_db.company_b) == 403
    # Old API redeployed by mistake: fails closed, cannot ignore the lifecycle.
    for subject, company in (
        ("alice-subject", legacy_db.company_a),
        ("bob-subject", legacy_db.company_b),
    ):
        with pytest.raises(ProgrammingError):
            old_api_authorizes(legacy_db, subject, company)

    # Database rollback is refused and changes nothing.
    refused = run_alembic(legacy_db.admin_url, "downgrade", B1A)
    assert refused.returncode != 0
    assert "roll forward" in refused.stderr
    assert revision(legacy_db) == B1B
    assert (
        admin_scalar(legacy_db, "SELECT status FROM users WHERE id = :id", id=legacy_db.alice)
        == "suspended"
    )

    # Even after everything is reactivated (all rows active again), the history
    # still refuses the rollback: the supported recovery is roll-forward.
    with operator_session(legacy_db) as session:
        service.reactivate_user(session, user_id=legacy_db.alice)
        service.reactivate_membership(
            session, company_id=legacy_db.company_b, membership_id=legacy_db.bob_membership
        )
    assert (
        admin_scalar(
            legacy_db,
            "SELECT (SELECT count(*) FROM users WHERE status <> 'active') "
            "+ (SELECT count(*) FROM memberships WHERE status <> 'active')",
        )
        == 0
    )
    still_refused = run_alembic(legacy_db.admin_url, "downgrade", B1A)
    assert still_refused.returncode != 0
    assert revision(legacy_db) == B1B
    with new_api(legacy_db) as client:
        assert new_api_status(client, "alice-subject", legacy_db.company_a) == 200
        assert new_api_status(client, "bob-subject", legacy_db.company_b) == 200


def test_post_b1_provisioning_blocks_rollback(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    with operator_session(legacy_db) as session:
        service.provision_member(
            session, company_id=legacy_db.company_a, issuer=LEGACY_ISSUER, subject="carol-subject"
        )

    refused = run_alembic(legacy_db.admin_url, "downgrade", B1A)
    assert refused.returncode != 0
    assert revision(legacy_db) == B1B


def test_rollback_without_any_lifecycle_history_restores_the_legacy_schema(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)

    assert run_alembic(legacy_db.admin_url, "downgrade", B1A).returncode == 0
    assert revision(legacy_db) == B1A
    assert (
        admin_scalar(
            legacy_db, "SELECT identity_subject FROM users WHERE id = :id", id=legacy_db.alice
        )
        == "alice-subject"
    )
    assert old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)

    assert run_alembic(legacy_db.admin_url, "downgrade", PRE_B1).returncode == 0
    assert admin_scalar(legacy_db, "SELECT to_regclass('public.user_identities')") is None
    assert old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)
    assert not old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_b)


def test_b1a_downgrade_refuses_audited_membership_changes(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    # An owner-made Membership after the backfill (attributed, so it is audited).
    with engine_for(legacy_db.admin_url) as engine, engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": REFERENCE}
        )
        conn.execute(
            text(
                "INSERT INTO memberships (id, company_id, user_id) "
                "VALUES (gen_random_uuid(), :b, :alice)"
            ),
            {"b": legacy_db.company_b, "alice": legacy_db.alice},
        )

    refused = run_alembic(legacy_db.admin_url, "downgrade", PRE_B1)
    assert refused.returncode != 0
    assert revision(legacy_db) == B1A


def test_b1b_refuses_users_without_a_matching_binding(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    # Drift: a User added outside the migration path has no binding.
    with engine_for(legacy_db.admin_url) as engine, engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": REFERENCE}
        )
        conn.execute(
            text("INSERT INTO users (id, identity_subject) VALUES (gen_random_uuid(), 'drift')")
        )

    result = run_alembic(legacy_db.admin_url, "upgrade", B1B)
    assert result.returncode != 0
    assert "reconcile them before B1b" in result.stderr
    assert revision(legacy_db) == B1A
    assert (
        admin_scalar(
            legacy_db,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'identity_subject'",
        )
        == 1
    )


def test_new_api_resolves_by_issuer_and_subject_not_subject_alone(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    with engine_for(legacy_db.runtime_url) as engine, Session(engine) as session:
        user = resolve_user(
            session, VerifiedIdentity(subject="alice-subject", issuer=LEGACY_ISSUER)
        )
        assert authorize_company(session, user, legacy_db.company_a).user_id == legacy_db.alice
        with pytest.raises(AuthorizationError):
            resolve_user(
                session, VerifiedIdentity(subject="alice-subject", issuer="https://other.test/")
            )
