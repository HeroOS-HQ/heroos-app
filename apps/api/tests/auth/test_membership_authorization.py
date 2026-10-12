"""Identity -> HeroOS User -> Membership resolution against real SQLAlchemy queries."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.exceptions import AuthorizationError
from app.auth.models import VerifiedIdentity
from app.auth.service import authorize_company, resolve_user
from app.db.models import User
from tests.auth.conftest import TEST_COGNITO_ISSUER, SeedData


def identity(subject: str) -> VerifiedIdentity:
    return VerifiedIdentity(subject=subject, issuer=TEST_COGNITO_ISSUER)


def test_identity_resolves_to_user_by_exact_issuer_and_subject(
    session_factory: sessionmaker[Session], seed: SeedData
) -> None:
    with session_factory() as db:
        resolved = resolve_user(db, identity("alice-subject"))
    assert resolved.user_id == seed.alice
    assert resolved.identity_id == seed.alice_identity


def test_unknown_identity_denied_without_provisioning(
    session_factory: sessionmaker[Session], seed: SeedData
) -> None:
    with session_factory() as db, pytest.raises(AuthorizationError):
        resolve_user(db, identity("unknown-subject"))

    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 3


def test_member_authorized_for_own_company(
    session_factory: sessionmaker[Session], seed: SeedData
) -> None:
    with session_factory() as db:
        user = resolve_user(db, identity("alice-subject"))
        context = authorize_company(db, user, seed.company_a)

    assert context.user_id == seed.alice
    assert context.company_id == seed.company_a
    assert context.membership_id == seed.alice_membership_a
    assert context.identity_id == seed.alice_identity


def test_member_of_company_a_denied_company_b(
    session_factory: sessionmaker[Session], seed: SeedData
) -> None:
    # Company B has a Membership (bob's): the lookup must be scoped to this user.
    with session_factory() as db:
        user = resolve_user(db, identity("alice-subject"))
        with pytest.raises(AuthorizationError):
            authorize_company(db, user, seed.company_b)


def test_user_without_any_membership_denied(
    session_factory: sessionmaker[Session], seed: SeedData
) -> None:
    with session_factory() as db:
        user = resolve_user(db, identity("carol-subject"))
        for company_id in (seed.company_a, seed.company_b):
            with pytest.raises(AuthorizationError):
                authorize_company(db, user, company_id)


def test_nonexistent_company_denied(session_factory: sessionmaker[Session], seed: SeedData) -> None:
    with session_factory() as db:
        user = resolve_user(db, identity("alice-subject"))
        with pytest.raises(AuthorizationError):
            authorize_company(db, user, uuid.uuid4())
