"""M1-05 Membership authorization under RLS: the candidate-scope bootstrap.

``memberships`` is tenant-protected, so ``authorize_company`` looks up this User's
Membership with the requested Company as a transaction-local candidate scope and
discards that scope before returning. An active Membership is the authorization.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.exceptions import AuthorizationError
from app.auth.models import VerifiedIdentity
from app.auth.service import authorize_company, resolve_user
from app.db.models import Membership
from app.tenancy.context import get_tenant_context, set_tenant_context
from tests.tenant_isolation.conftest import (
    SERVICE_TEST_ISSUER,
    TENANT_TABLES,
    Tenants,
    count_rows,
    owners,
)


def identity(subject: str) -> VerifiedIdentity:
    return VerifiedIdentity(subject=subject, issuer=SERVICE_TEST_ISSUER)


def _assert_no_tenant_data_left_visible(db: Session) -> None:
    assert get_tenant_context(db) is None
    for table in TENANT_TABLES:
        assert count_rows(db, table) == 0


def test_member_is_authorized_with_trusted_context(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db:
        user = resolve_user(db, identity("alice-subject"))
        context = authorize_company(db, user, tenants.a.company)

        assert context.user_id == tenants.a.user
        assert context.company_id == tenants.a.company
        assert context.membership_id == tenants.a.membership
        assert context.identity_id == tenants.a.identity
        # The candidate scope ended with the lookup.
        _assert_no_tenant_data_left_visible(db)


@pytest.mark.parametrize(
    ("subject", "target"),
    [
        pytest.param("alice-subject", "b", id="cross-company"),
        pytest.param("bob-subject", "a", id="cross-company-reverse"),
        pytest.param("carol-subject", "a", id="no-membership"),
        pytest.param("alice-subject", "missing", id="nonexistent-company"),
        pytest.param("alice-subject", "nil", id="nil-company"),
    ],
)
def test_denials_leave_no_tenant_scope_behind(
    runtime_sessions: sessionmaker[Session], tenants: Tenants, subject: str, target: str
) -> None:
    company = {
        "a": tenants.a.company,
        "b": tenants.b.company,
        "missing": uuid.uuid4(),
        "nil": uuid.UUID(int=0),
    }[target]
    with runtime_sessions() as db:
        user = resolve_user(db, identity(subject))
        with pytest.raises(AuthorizationError):
            authorize_company(db, user, company)

        _assert_no_tenant_data_left_visible(db)


def test_unknown_identity_is_denied(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    with runtime_sessions() as db, pytest.raises(AuthorizationError):
        resolve_user(db, identity("stranger"))


def test_memberships_are_not_globally_readable(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # Without a scope even the caller's own Membership is invisible: the
    # bootstrap needs the candidate scope, and nothing else can read memberships.
    with runtime_sessions() as db:
        own = db.scalar(select(Membership).where(Membership.user_id == tenants.a.user))
        assert own is None
        assert count_rows(db, "memberships") == 0


def test_candidate_scope_exposes_only_the_requested_company(
    runtime_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    # Alice requesting Company B: the candidate scope shows only Company B's
    # rows, and alice has no Membership among them, so she is denied.
    with runtime_sessions() as db:
        set_tenant_context(db, tenants.b.company)
        assert owners(db, "memberships") == {tenants.b.company}
        assert (
            db.scalar(
                select(Membership).where(
                    Membership.user_id == tenants.a.user,
                    Membership.company_id == tenants.b.company,
                )
            )
            is None
        )
        db.rollback()
