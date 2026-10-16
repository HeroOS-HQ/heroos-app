"""Migrations B1a/B1b: backfill contract, API compatibility and rollback safety.

Every test gets its own disposable ``*_tenant_isolation_test`` database seeded
with legacy data at ``97d4200fe7a2`` (two Companies, alice and bob), then
migrates it with Alembic exactly as an operator would.

- **Old API**: the frozen ``371dd50`` authorization code (``legacy_371dd50``),
  running as the API runtime role.
- **M1-10B API**: the frozen ``169261d`` code (``legacy_169261d``), the API that
  B1a and B1b were designed for, running as the API runtime role.
- **Current API** (M1-10C): requires migration C1; see
  ``test_company_migration.py`` for its compatibility matrix.

Compatibility matrix (M1-10B acceptance):

    old API + B1a -> works        M1-10B API + B1a -> works
    old API + B1b -> fails closed M1-10B API + B1b -> works
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import VerifiedIdentity
from app.auth.service import authorize_company, resolve_user
from app.db.runtime_role import (
    API_MINIMUM_SCHEMA_CONTRACT,
    IncompatibleSchemaError,
    verify_runtime_role,
)
from tests.tenant_isolation.conftest import (
    LegacyDatabase,
    TenantDatabase,
    disposable_database,
    run_alembic,
)
from tests.tenant_isolation.migration_helpers import (
    B1A,
    B1B,
    C1,
    D1,
    D2,
    D3,
    LEGACY_ISSUER,
    PRE_B1,
    REFERENCE,
    admin_scalar,
    b1a,
    b1b,
    engine_for,
    m110b_api_status,
    old_api_authorizes,
    operator_sql,
    revision,
    upgrade,
)

REVOKE_MEMBERSHIP = (
    "UPDATE memberships SET status = 'revoked', revoked_at = now() WHERE id = :membership"
)
REACTIVATE_MEMBERSHIP = (
    "UPDATE memberships SET status = 'active', revoked_at = NULL WHERE id = :membership"
)
SUSPEND_USER = "UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :user"
REACTIVATE_USER = "UPDATE users SET status = 'active', suspended_at = NULL WHERE id = :user"


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


def test_m110b_api_works_on_b1a(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)

    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 200
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_b) == 200
    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_b) == 403
    assert m110b_api_status(legacy_db, "stranger", legacy_db.company_a) == 403


def test_m110b_api_works_on_b1b(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)

    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 200
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_b) == 200
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_a) == 403


def test_old_api_fails_closed_on_b1b(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)

    # The old ORM mapping selects users.identity_subject, which no longer exists:
    # every protected request errors (HTTP 500 at the error boundary) and no
    # Company context is ever produced.
    with pytest.raises(ProgrammingError) as exc_info:
        old_api_authorizes(legacy_db, "alice-subject", legacy_db.company_a)
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42703"


def test_current_api_requires_the_d3_schema_contract(legacy_db: LegacyDatabase) -> None:
    with engine_for(legacy_db.runtime_url) as engine:
        # Pre-B1a, B1a, B1b, C1, D1 and D2 schemas: the current API refuses to
        # start rather than fail per request (it maps memberships.role, the
        # M2-01 workflow tables, the M2-02 intake evaluations and, since M2-03,
        # the progress events).
        with pytest.raises(IncompatibleSchemaError):
            verify_runtime_role(engine)
        b1a(legacy_db)
        with pytest.raises(IncompatibleSchemaError, match="contract is 1"):
            verify_runtime_role(engine)
        b1b(legacy_db)
        with pytest.raises(IncompatibleSchemaError, match="contract is 2"):
            verify_runtime_role(engine)
        upgrade(legacy_db, C1)
        with pytest.raises(IncompatibleSchemaError, match="contract is 3"):
            verify_runtime_role(engine)
        upgrade(legacy_db, D1)
        with pytest.raises(IncompatibleSchemaError, match="contract is 4"):
            verify_runtime_role(engine)
        upgrade(legacy_db, D2)
        with pytest.raises(IncompatibleSchemaError, match="contract is 5"):
            verify_runtime_role(engine)
        upgrade(legacy_db, D3)
        verify_runtime_role(engine)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT heroos_schema_contract()")) == 6
    assert API_MINIMUM_SCHEMA_CONTRACT == 6


# --- revocation and rollback --------------------------------------------------------


def test_revoked_access_stays_denied_through_the_supported_recovery_procedure(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    operator_sql(
        legacy_db,
        REVOKE_MEMBERSHIP,
        company=legacy_db.company_b,
        membership=legacy_db.bob_membership,
    )
    operator_sql(legacy_db, SUSPEND_USER, user=legacy_db.alice)

    # M1-10B API: both denied on the next request.
    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 403
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_b) == 403
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
    operator_sql(legacy_db, REACTIVATE_USER, user=legacy_db.alice)
    operator_sql(
        legacy_db,
        REACTIVATE_MEMBERSHIP,
        company=legacy_db.company_b,
        membership=legacy_db.bob_membership,
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
    assert m110b_api_status(legacy_db, "alice-subject", legacy_db.company_a) == 200
    assert m110b_api_status(legacy_db, "bob-subject", legacy_db.company_b) == 200


def test_post_b1_provisioning_blocks_rollback(legacy_db: LegacyDatabase) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    # What `provision` writes: a User, its binding and a Membership.
    operator_sql(
        legacy_db,
        "INSERT INTO users (id) VALUES (:carol)",
        "INSERT INTO user_identities (id, user_id, issuer, subject) "
        "VALUES (gen_random_uuid(), :carol, :issuer, 'carol-subject')",
        "INSERT INTO memberships (id, company_id, user_id) VALUES (gen_random_uuid(), :a, :carol)",
        company=legacy_db.company_a,
        carol=uuid.uuid4(),
        issuer=LEGACY_ISSUER,
        a=legacy_db.company_a,
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


def test_current_api_resolves_by_issuer_and_subject_not_subject_alone(
    legacy_db: LegacyDatabase,
) -> None:
    b1a(legacy_db)
    b1b(legacy_db)
    upgrade(legacy_db, C1)
    with engine_for(legacy_db.runtime_url) as engine, Session(engine) as session:
        user = resolve_user(
            session, VerifiedIdentity(subject="alice-subject", issuer=LEGACY_ISSUER)
        )
        assert authorize_company(session, user, legacy_db.company_a).user_id == legacy_db.alice
        with pytest.raises(AuthorizationError):
            resolve_user(
                session, VerifiedIdentity(subject="alice-subject", issuer="https://other.test/")
            )
