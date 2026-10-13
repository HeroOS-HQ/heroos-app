"""Operator provisioning and lifecycle (app.identity.service) on PostgreSQL.

Every change runs as the identity-operator role; every access decision is then
checked through the new authorization path as the API runtime role.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import VerifiedIdentity
from app.auth.service import authorize_company, resolve_user
from app.identity import errors, service
from app.identity.errors import IdentityOperationError
from app.identity.operator import set_actor_reference
from app.tenancy.context import get_tenant_context
from tests.tenant_isolation.conftest import (
    OIDC_TEST_ISSUER,
    SERVICE_TEST_ISSUER,
    TEST_REFERENCE,
    Tenants,
)

ISSUER = SERVICE_TEST_ISSUER


@contextmanager
def operator_tx(engine: Engine, reference: str = TEST_REFERENCE) -> Iterator[Session]:
    with Session(engine, autoflush=False) as session:
        set_actor_reference(session, reference)
        yield session
        session.commit()


def can_access(
    runtime_engine: Engine, subject: str, company: uuid.UUID, issuer: str = ISSUER
) -> bool:
    with Session(runtime_engine) as session:
        try:
            user = resolve_user(session, VerifiedIdentity(subject=subject, issuer=issuer))
            authorize_company(session, user, company)
        except AuthorizationError:
            return False
        return True


def events(admin_engine: Engine) -> dict[str, tuple[str, ...]]:
    """Every audit event by id: (event_type, actor_kind, actor_reference, txid)."""
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id::text, event_type, actor_kind, actor_reference, txid::text "
                "FROM identity_events UNION ALL "
                "SELECT id::text, event_type, actor_kind, actor_reference, txid::text "
                "FROM membership_events"
            )
        ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def new_events(before: dict[str, tuple[str, ...]], admin_engine: Engine) -> list[tuple[str, ...]]:
    return [event for key, event in events(admin_engine).items() if key not in before]


def test_provision_creates_user_binding_and_membership_atomically(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    before = events(admin_engine)
    with operator_tx(operator_engine) as session:
        result = service.provision_member(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="dana-subject"
        )

    assert result.outcome == service.CREATED
    assert set(result.ids) == {"user_id", "identity_id", "membership_id"}
    assert can_access(runtime_engine, "dana-subject", tenants.a.company)
    assert not can_access(runtime_engine, "dana-subject", tenants.b.company)

    new = new_events(before, admin_engine)
    assert sorted(e[0] for e in new) == ["identity_bound", "membership_granted", "user_created"]
    assert {(e[1], e[2]) for e in new} == {("operator", TEST_REFERENCE)}
    assert len({e[3] for e in new}) == 1  # one transaction


def test_provision_is_idempotent_and_never_merges_people(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with operator_tx(operator_engine) as session:
        first = service.provision_member(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="erin-subject"
        )
    count = len(events(admin_engine))

    with operator_tx(operator_engine) as session:
        again = service.provision_member(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="erin-subject"
        )
    assert (again.outcome, again.ids) == (service.UNCHANGED, first.ids)
    assert len(events(admin_engine)) == count

    # The same identity for another Company is an explicit grant, never a
    # silent second User.
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.provision_member(
            session, company_id=tenants.b.company, issuer=ISSUER, subject="erin-subject"
        )
    assert exc.value.code == errors.IDENTITY_EXISTS
    with operator_tx(operator_engine) as session:
        granted = service.grant_membership(
            session, company_id=tenants.b.company, issuer=ISSUER, subject="erin-subject"
        )
    assert granted.outcome == service.CREATED
    assert granted.ids["user_id"] == first.ids["user_id"]


def test_failed_provisioning_leaves_no_user_binding_access_or_event(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    before = events(admin_engine)
    with Session(operator_engine) as session:
        set_actor_reference(session, TEST_REFERENCE)
        service.provision_member(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="fail-subject"
        )
        session.rollback()  # e.g. the operator aborts, or anything fails before commit

    with pytest.raises(IdentityOperationError) as exc, operator_tx(operator_engine) as session:
        service.provision_member(
            session, company_id=uuid.uuid4(), issuer=ISSUER, subject="fail-subject"
        )
    assert exc.value.code == errors.COMPANY_NOT_FOUND

    assert not can_access(runtime_engine, "fail-subject", tenants.a.company)
    with admin_engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT count(*) FROM user_identities WHERE subject = 'fail-subject'"))
            == 0
        )
    assert new_events(before, admin_engine) == []


def test_change_without_reference_is_rolled_back_with_its_audit(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with Session(operator_engine) as session, pytest.raises(DBAPIError):
        service.provision_member(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="noref-subject"
        )
    with admin_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM users")) == 3


def test_bindings_are_never_reassigned_or_duplicated(
    operator_engine: Engine, tenants: Tenants
) -> None:
    # alice's binding cannot be bound to bob ...
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.bind_identity(
            session, user_id=tenants.b.user, issuer=ISSUER, subject="alice-subject"
        )
    assert exc.value.code == errors.IDENTITY_CONFLICT
    # ... bob cannot get a second active binding for the same issuer ...
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.bind_identity(session, user_id=tenants.b.user, issuer=ISSUER, subject="bob-2")
    assert exc.value.code == errors.ACTIVE_IDENTITY_EXISTS_FOR_ISSUER
    # ... and the database enforces both even without the service checks.
    for subject, user in (("alice-subject", tenants.b.user), ("bob-2", tenants.b.user)):
        with operator_engine.connect() as conn, pytest.raises(IntegrityError):
            set_reference = "SELECT set_config('heroos.actor_reference', 'HER-230', true)"
            conn.execute(text(set_reference))
            conn.execute(
                text(
                    "INSERT INTO user_identities (id, user_id, issuer, subject) "
                    "VALUES (gen_random_uuid(), :u, :i, :s)"
                ),
                {"u": user, "i": ISSUER, "s": subject},
            )


def test_revoked_membership_is_denied_and_other_companies_keep_working(
    operator_engine: Engine, runtime_engine: Engine, tenants: Tenants
) -> None:
    with operator_tx(operator_engine) as session:
        service.grant_membership(
            session, company_id=tenants.b.company, issuer=ISSUER, subject="alice-subject"
        )
    assert can_access(runtime_engine, "alice-subject", tenants.b.company)

    with operator_tx(operator_engine) as session:
        service.revoke_membership(
            session, company_id=tenants.a.company, membership_id=tenants.a.membership
        )
    assert not can_access(runtime_engine, "alice-subject", tenants.a.company)
    assert can_access(runtime_engine, "alice-subject", tenants.b.company)

    # A revoked Membership is reactivated explicitly, never re-granted silently.
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.grant_membership(
            session, company_id=tenants.a.company, issuer=ISSUER, subject="alice-subject"
        )
    assert exc.value.code == errors.MEMBERSHIP_REVOKED
    with operator_tx(operator_engine) as session:
        service.reactivate_membership(
            session, company_id=tenants.a.company, membership_id=tenants.a.membership
        )
    assert can_access(runtime_engine, "alice-subject", tenants.a.company)


def test_suspended_user_is_denied_everywhere_until_reactivated(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with operator_tx(operator_engine) as session:
        service.suspend_user(session, user_id=tenants.a.user)
    for issuer in (ISSUER, OIDC_TEST_ISSUER):
        assert not can_access(runtime_engine, "alice-subject", tenants.a.company, issuer)

    # Suspension is not deletion: the User, its bindings and its Membership remain.
    with admin_engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT u.status, m.status FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE u.id = :u"
            ),
            {"u": tenants.a.user},
        ).one() == ("suspended", "active")

    with operator_tx(operator_engine) as session:
        assert service.reactivate_user(session, user_id=tenants.a.user).outcome == service.UPDATED
    assert can_access(runtime_engine, "alice-subject", tenants.a.company)


def test_revoked_identity_is_denied_while_another_issuer_still_works(
    operator_engine: Engine, runtime_engine: Engine, tenants: Tenants
) -> None:
    with operator_tx(operator_engine) as session:
        service.revoke_identity(session, identity_id=tenants.a.identity)

    assert not can_access(runtime_engine, "alice-subject", tenants.a.company, ISSUER)
    assert can_access(runtime_engine, "alice-subject", tenants.a.company, OIDC_TEST_ISSUER)

    # A revoked binding can never be bound again, to anyone.
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.bind_identity(
            session, user_id=tenants.a.user, issuer=ISSUER, subject="alice-subject"
        )
    assert exc.value.code == errors.IDENTITY_CONFLICT

    with operator_tx(operator_engine) as session:
        service.reactivate_identity(session, identity_id=tenants.a.identity)
    assert can_access(runtime_engine, "alice-subject", tenants.a.company, ISSUER)


def test_operator_cannot_act_on_another_companys_membership(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        # Company A scope, Company B's Membership id: invisible under RLS.
        service.revoke_membership(
            session, company_id=tenants.a.company, membership_id=tenants.b.membership
        )
    assert exc.value.code == errors.MEMBERSHIP_NOT_FOUND
    with admin_engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM memberships WHERE id = :m"), {"m": tenants.b.membership}
            )
            == "active"
        )


def test_operator_scope_never_outlives_its_transaction(
    operator_engine: Engine, tenants: Tenants
) -> None:
    with Session(operator_engine) as session:
        set_actor_reference(session, TEST_REFERENCE)
        service.revoke_membership(
            session, company_id=tenants.a.company, membership_id=tenants.a.membership
        )
        session.commit()
        assert get_tenant_context(session) is None
        assert session.scalar(text("SELECT current_setting('heroos.actor_reference', true)")) in (
            None,
            "",
        )


@pytest.mark.parametrize(
    ("issuer", "subject"),
    [
        ("http://idp.test/", "x"),
        ("https://idp.test/?q=1", "x"),
        ("https://idp.test/ ", "x"),
        (ISSUER, ""),
        (ISSUER, " padded"),
        (ISSUER, "line\nbreak"),
        (ISSUER, "x" * 256),
        ("a@example.com", "x"),
    ],
)
def test_invalid_issuers_and_subjects_are_refused_not_normalized(
    operator_engine: Engine, tenants: Tenants, issuer: str, subject: str
) -> None:
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.provision_member(
            session, company_id=tenants.a.company, issuer=issuer, subject=subject
        )
    assert exc.value.code == errors.INVALID_INPUT
