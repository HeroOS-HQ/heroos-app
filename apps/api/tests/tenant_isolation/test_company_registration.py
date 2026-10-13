"""Trusted Company registration and administrator assignment on PostgreSQL (M1-10C).

Every change runs as the identity-operator role through ``app.identity``; every
access decision is then checked through the API authorization path as the API
runtime role. Ground truth is read as the migration owner.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext, VerifiedIdentity
from app.auth.service import authorize_company, is_active_company_admin, resolve_user
from app.identity import companies, errors, service
from app.identity.errors import IdentityOperationError
from app.identity.operator import set_actor_reference
from app.tenancy.scope import open_company_scope
from tests.tenant_isolation.conftest import SERVICE_TEST_ISSUER, TEST_REFERENCE, Tenants

ISSUER = SERVICE_TEST_ISSUER
REGISTRATION_REFERENCE = "HER-232"


@contextmanager
def operator_tx(engine: Engine, reference: str = REGISTRATION_REFERENCE) -> Iterator[Session]:
    with Session(engine, autoflush=False) as session:
        set_actor_reference(session, reference)
        yield session
        session.commit()


def register(
    engine: Engine,
    company: uuid.UUID,
    subject: str,
    *,
    name: str = "Gamma Trading",
    existing_user: bool = False,
) -> service.OperationResult:
    with operator_tx(engine) as session:
        return companies.register_company(
            session,
            company_id=company,
            name=name,
            issuer=ISSUER,
            subject=subject,
            existing_user=existing_user,
        )


def context_for(
    runtime_engine: Engine, subject: str, company: uuid.UUID
) -> AuthenticatedCompanyContext:
    with Session(runtime_engine) as session:
        user = resolve_user(session, VerifiedIdentity(subject=subject, issuer=ISSUER))
        return authorize_company(session, user, company)


def events(admin_engine: Engine) -> list[tuple[str, ...]]:
    """Every audit event: (table, event_type, actor_kind, reference, txid, detail)."""
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT 'identity', event_type, actor_kind, actor_reference, txid::text, '' "
                "FROM identity_events UNION ALL "
                "SELECT 'membership', event_type, actor_kind, actor_reference, txid::text, "
                "coalesce(role, '') FROM membership_events UNION ALL "
                "SELECT 'company', event_type, actor_kind, actor_reference, txid::text, "
                "coalesce(jurisdiction, '') FROM company_events"
            )
        ).all()
    return [tuple(row) for row in rows]


def counts(admin_engine: Engine, company: uuid.UUID) -> dict[str, int]:
    with admin_engine.connect() as conn:
        return {
            table: conn.scalar(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :c"), {"c": company}
            )
            for table, column in (
                ("companies", "id"),
                ("company_blueprints", "company_id"),
                ("memberships", "company_id"),
                ("membership_events", "company_id"),
                ("company_events", "company_id"),
            )
        }


def subject_count(admin_engine: Engine, subject: str) -> int:
    with admin_engine.connect() as conn:
        count: int = conn.scalar(
            text("SELECT count(*) FROM user_identities WHERE subject = :s"), {"s": subject}
        )
    return count


# --- registration ------------------------------------------------------------------


def test_registration_creates_company_blueprint_and_administrator_in_one_transaction(
    operator_engine: Engine,
    runtime_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    tenant_database: object,
) -> None:
    before = events(admin_engine)
    company = uuid.uuid4()

    result = register(operator_engine, company, "gina-subject")

    assert result.outcome == service.CREATED
    assert set(result.ids) == {
        "company_id",
        "blueprint_id",
        "user_id",
        "identity_id",
        "membership_id",
    }
    assert result.ids["company_id"] == company
    with admin_engine.connect() as conn:
        name = conn.scalar(text("SELECT name FROM companies WHERE id = :c"), {"c": company})
        blueprint = conn.execute(
            text(
                "SELECT id, legal_name, licensing_location, employment_jurisdiction "
                "FROM company_blueprints WHERE company_id = :c"
            ),
            {"c": company},
        ).one()
        membership = conn.execute(
            text("SELECT user_id, status, role FROM memberships WHERE company_id = :c"),
            {"c": company},
        ).one()
    assert name == "Gamma Trading"
    # An empty Blueprint: nothing about the Company's licensing is assumed.
    assert tuple(blueprint) == (result.ids["blueprint_id"], None, None, None)
    assert tuple(membership) == (result.ids["user_id"], "active", "company_admin")

    new = [event for event in events(admin_engine) if event not in before]
    assert sorted((e[0], e[1], e[5]) for e in new) == [
        ("company", "company_registered", ""),
        ("identity", "identity_bound", ""),
        ("identity", "user_created", ""),
        ("membership", "membership_granted", "company_admin"),
    ]
    assert {(e[2], e[3]) for e in new} == {("operator", REGISTRATION_REFERENCE)}
    assert len({e[4] for e in new}) == 1  # one transaction

    # The new administrator reaches the new Company, and only it, as an admin.
    context = context_for(runtime_engine, "gina-subject", company)
    assert (context.company_id, context.role) == (company, "company_admin")
    with Session(runtime_engine) as session:
        open_company_scope(session, context)
        assert is_active_company_admin(session, context)
    for other in (tenants.a.company, tenants.b.company):
        with pytest.raises(AuthorizationError):
            context_for(runtime_engine, "gina-subject", other)


def test_registration_retry_reports_unchanged_and_writes_nothing(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    company = uuid.uuid4()
    first = register(operator_engine, company, "hana-subject")
    snapshot = (events(admin_engine), counts(admin_engine, company))

    # Same command again (e.g. the operator's connection dropped after commit),
    # even with a corrected name: the stable UUID decides, nothing is duplicated.
    again = register(operator_engine, company, "hana-subject", name="Gamma Trading FZ-LLC")

    assert again.outcome == service.UNCHANGED
    assert {k: again.ids[k] for k in ("company_id", "user_id", "identity_id", "membership_id")} == {
        k: first.ids[k] for k in ("company_id", "user_id", "identity_id", "membership_id")
    }
    assert (events(admin_engine), counts(admin_engine, company)) == snapshot
    assert counts(admin_engine, company) == {
        "companies": 1,
        "company_blueprints": 1,
        "memberships": 1,
        "membership_events": 1,
        "company_events": 1,
    }


def test_an_existing_company_cannot_be_claimed_by_registering_it_again(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    # Knowing a Company's UUID (or name) establishes nothing: registering an
    # existing Company for another identity is refused, for seeded and newly
    # registered Companies alike.
    company = uuid.uuid4()
    register(operator_engine, company, "ivan-subject")
    for target, subject, existing in (
        (company, "mallory-subject", False),
        (tenants.a.company, "mallory-subject", False),
        (tenants.a.company, "bob-subject", True),
        (company, "alice-subject", True),
    ):
        with pytest.raises(IdentityOperationError) as exc_info:
            register(operator_engine, target, subject, existing_user=existing)
        assert exc_info.value.code == errors.COMPANY_EXISTS

    assert subject_count(admin_engine, "mallory-subject") == 0
    with pytest.raises(AuthorizationError):
        context_for(runtime_engine, "bob-subject", tenants.a.company)
    # A member of A (alice) does not become anyone's administrator.
    assert context_for(runtime_engine, "alice-subject", tenants.a.company).role == "member"


def test_an_existing_user_can_administer_a_newly_registered_company(
    operator_engine: Engine, runtime_engine: Engine, tenants: Tenants
) -> None:
    company = uuid.uuid4()
    result = register(operator_engine, company, "alice-subject", existing_user=True)

    assert result.outcome == service.CREATED
    assert result.ids["user_id"] == tenants.a.user
    assert result.ids["identity_id"] == tenants.a.identity
    assert context_for(runtime_engine, "alice-subject", company).role == "company_admin"
    # Her role elsewhere is unchanged: roles are per Company.
    assert context_for(runtime_engine, "alice-subject", tenants.a.company).role == "member"


@pytest.mark.parametrize(
    ("subject", "existing_user", "code"),
    [
        # A bound identity is never silently reused as a "new" administrator.
        ("alice-subject", False, errors.IDENTITY_EXISTS),
        ("nobody-subject", True, errors.IDENTITY_NOT_FOUND),
    ],
)
def test_registration_never_merges_or_invents_people(
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    subject: str,
    existing_user: bool,
    code: str,
) -> None:
    company = uuid.uuid4()
    with pytest.raises(IdentityOperationError) as exc_info:
        register(operator_engine, company, subject, existing_user=existing_user)

    assert exc_info.value.code == code
    assert counts(admin_engine, company)["companies"] == 0


@pytest.mark.parametrize("lifecycle", ["suspended-user", "revoked-identity"])
def test_registration_refuses_inactive_administrators(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants, lifecycle: str
) -> None:
    with operator_tx(operator_engine) as session:
        if lifecycle == "suspended-user":
            service.suspend_user(session, user_id=tenants.a.user)
        else:
            service.revoke_identity(session, identity_id=tenants.a.identity)

    company = uuid.uuid4()
    with pytest.raises(IdentityOperationError) as exc_info:
        register(operator_engine, company, "alice-subject", existing_user=True)

    expected = errors.USER_SUSPENDED if lifecycle == "suspended-user" else errors.IDENTITY_REVOKED
    assert exc_info.value.code == expected
    assert counts(admin_engine, company)["companies"] == 0


@pytest.mark.parametrize(
    ("company", "name", "issuer", "subject"),
    [
        (uuid.uuid4(), "", ISSUER, "x-subject"),
        (uuid.uuid4(), " Padded", ISSUER, "x-subject"),
        (uuid.uuid4(), "Line\nbreak", ISSUER, "x-subject"),
        (uuid.uuid4(), "x" * 201, ISSUER, "x-subject"),
        (uuid.UUID(int=0), "Nil", ISSUER, "x-subject"),
        (uuid.uuid4(), "Gamma", "http://idp.test/", "x-subject"),
        (uuid.uuid4(), "Gamma", ISSUER, " padded"),
        (uuid.uuid4(), "Gamma", "a@example.com", "x-subject"),
    ],
)
def test_invalid_registration_input_is_refused_not_normalized(
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    company: uuid.UUID,
    name: str,
    issuer: str,
    subject: str,
) -> None:
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        companies.register_company(
            session, company_id=company, name=name, issuer=issuer, subject=subject
        )
    assert exc.value.code == errors.INVALID_INPUT
    assert counts(admin_engine, company)["companies"] == 0


def test_a_failure_at_the_last_step_leaves_no_company_blueprint_user_or_event(
    operator_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The administrator Membership is written last; make the database refuse it
    # (CHECK ck_memberships_role) after the Company, Blueprint, User and binding
    # were already flushed in the same transaction.
    monkeypatch.setattr(companies, "ROLE_COMPANY_ADMIN", "owner")
    before = events(admin_engine)
    company = uuid.uuid4()

    with pytest.raises(IntegrityError), Session(operator_engine, autoflush=False) as session:
        set_actor_reference(session, REGISTRATION_REFERENCE)
        companies.register_company(
            session, company_id=company, name="Doomed", issuer=ISSUER, subject="doomed-subject"
        )

    assert counts(admin_engine, company) == dict.fromkeys(
        ("companies", "company_blueprints", "memberships", "membership_events", "company_events"),
        0,
    )
    assert subject_count(admin_engine, "doomed-subject") == 0
    assert events(admin_engine) == before


def test_registration_without_a_change_reference_is_rejected_with_its_audit(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    company = uuid.uuid4()
    with Session(operator_engine) as session, pytest.raises(DBAPIError) as exc_info:
        companies.register_company(
            session, company_id=company, name="Unattributed", issuer=ISSUER, subject="u-subject"
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "22023"
    assert counts(admin_engine, company)["companies"] == 0


def test_the_api_role_cannot_register_a_company(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    company = uuid.uuid4()
    with Session(runtime_engine, autoflush=False) as session, pytest.raises(DBAPIError) as exc:
        set_actor_reference(session, TEST_REFERENCE)
        companies.register_company(
            session, company_id=company, name="Rogue", issuer=ISSUER, subject="rogue-subject"
        )
    assert getattr(exc.value.orig, "sqlstate", None) == "42501"
    assert counts(admin_engine, company)["companies"] == 0
    assert subject_count(admin_engine, "rogue-subject") == 0


def _wait_for_lock_wait(admin_engine: Engine, timeout: float = 20.0) -> None:
    """Block until some backend of this database waits on a lock."""
    deadline = time.monotonic() + timeout
    with admin_engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            if waiting:
                return
            conn.rollback()
            time.sleep(0.05)
    raise AssertionError("the concurrent registration never waited on the first one")


@pytest.mark.parametrize("race", ["same-company", "same-administrator"])
def test_concurrent_registrations_never_duplicate(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants, race: str
) -> None:
    first_company = uuid.uuid4()
    second_company = first_company if race == "same-company" else uuid.uuid4()
    second_subject = "racer-2-subject" if race == "same-company" else "racer-1-subject"
    outcome: list[object] = []

    def second() -> None:
        with Session(operator_engine, autoflush=False) as session:
            set_actor_reference(session, REGISTRATION_REFERENCE)
            try:
                companies.register_company(
                    session,
                    company_id=second_company,
                    name="Racer Two",
                    issuer=ISSUER,
                    subject=second_subject,
                )
                session.commit()
                outcome.append("committed")
            except IntegrityError as exc:
                session.rollback()
                outcome.append(getattr(exc.orig, "sqlstate", None))

    with Session(operator_engine, autoflush=False) as first:
        set_actor_reference(first, REGISTRATION_REFERENCE)
        companies.register_company(
            first,
            company_id=first_company,
            name="Racer One",
            issuer=ISSUER,
            subject="racer-1-subject",
        )
        # The second registration passes its own checks (the first is not
        # committed yet) and then waits on the first one's unique key.
        thread = threading.Thread(target=second)
        thread.start()
        _wait_for_lock_wait(admin_engine)
        first.commit()
    thread.join(timeout=30)

    # The loser is refused by the database (unique violation), so the CLI
    # reports registration_conflict_rerun; nothing of it remains.
    assert outcome == ["23505"]
    assert counts(admin_engine, first_company) == {
        "companies": 1,
        "company_blueprints": 1,
        "memberships": 1,
        "membership_events": 1,
        "company_events": 1,
    }
    assert subject_count(admin_engine, "racer-1-subject") == 1
    if race == "same-company":
        assert subject_count(admin_engine, "racer-2-subject") == 0
    else:
        assert counts(admin_engine, second_company)["companies"] == 0

    # Re-running the losing command now gives a definite answer.
    with pytest.raises(IdentityOperationError) as exc_info:
        register(operator_engine, second_company, second_subject)
    expected = errors.COMPANY_EXISTS if race == "same-company" else errors.IDENTITY_EXISTS
    assert exc_info.value.code == expected
    assert register(operator_engine, first_company, "racer-1-subject").outcome == service.UNCHANGED


# --- administrator assignment --------------------------------------------------------


def test_operator_appoints_and_removes_an_administrator_with_audit(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    # Bootstrap for a Company that existed before roles: alice is a member.
    assert context_for(runtime_engine, "alice-subject", tenants.a.company).role == "member"
    before = events(admin_engine)

    with operator_tx(operator_engine) as session:
        promoted = service.set_membership_role(
            session,
            company_id=tenants.a.company,
            membership_id=tenants.a.membership,
            role="company_admin",
        )
    assert (promoted.outcome, promoted.details) == (service.UPDATED, {"role": "company_admin"})
    assert context_for(runtime_engine, "alice-subject", tenants.a.company).role == "company_admin"
    # Roles are per Company: nothing changes for B.
    assert context_for(runtime_engine, "bob-subject", tenants.b.company).role == "member"

    with operator_tx(operator_engine) as session:
        again = service.set_membership_role(
            session,
            company_id=tenants.a.company,
            membership_id=tenants.a.membership,
            role="company_admin",
        )
    assert again.outcome == service.UNCHANGED

    with operator_tx(operator_engine) as session:
        service.set_membership_role(
            session,
            company_id=tenants.a.company,
            membership_id=tenants.a.membership,
            role="member",
        )
    assert context_for(runtime_engine, "alice-subject", tenants.a.company).role == "member"

    new = [event for event in events(admin_engine) if event not in before]
    assert sorted((e[0], e[1], e[2], e[3], e[5]) for e in new) == [
        (
            "membership",
            "membership_role_changed",
            "operator",
            REGISTRATION_REFERENCE,
            "company_admin",
        ),
        ("membership", "membership_role_changed", "operator", REGISTRATION_REFERENCE, "member"),
    ]


def test_role_changes_stay_within_one_company_and_active_memberships(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    # Company A scope, Company B's Membership: invisible under RLS.
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.set_membership_role(
            session,
            company_id=tenants.a.company,
            membership_id=tenants.b.membership,
            role="company_admin",
        )
    assert exc.value.code == errors.MEMBERSHIP_NOT_FOUND

    # A revoked Membership is reactivated explicitly first, never via a role change.
    with operator_tx(operator_engine) as session:
        service.revoke_membership(
            session, company_id=tenants.a.company, membership_id=tenants.a.membership
        )
    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.set_membership_role(
            session,
            company_id=tenants.a.company,
            membership_id=tenants.a.membership,
            role="company_admin",
        )
    assert exc.value.code == errors.MEMBERSHIP_REVOKED

    with operator_tx(operator_engine) as session, pytest.raises(IdentityOperationError) as exc:
        service.set_membership_role(
            session, company_id=tenants.b.company, membership_id=tenants.b.membership, role="owner"
        )
    assert exc.value.code == errors.INVALID_INPUT

    with admin_engine.connect() as conn:
        roles = set(conn.scalars(text("SELECT role FROM memberships")))
    assert roles == {"member"}


def test_revoked_and_suspended_administrators_lose_access_on_the_next_request(
    operator_engine: Engine, runtime_engine: Engine, tenants: Tenants
) -> None:
    company = uuid.uuid4()
    result = register(operator_engine, company, "kara-subject")
    context = context_for(runtime_engine, "kara-subject", company)

    with operator_tx(operator_engine) as session:
        service.revoke_membership(
            session, company_id=company, membership_id=result.ids["membership_id"]
        )
    with pytest.raises(AuthorizationError):
        context_for(runtime_engine, "kara-subject", company)
    # A context obtained before the revocation no longer passes the write check.
    with Session(runtime_engine) as session:
        open_company_scope(session, context)
        assert not is_active_company_admin(session, context)

    with operator_tx(operator_engine) as session:
        service.reactivate_membership(
            session, company_id=company, membership_id=result.ids["membership_id"]
        )
        service.suspend_user(session, user_id=result.ids["user_id"])
    with pytest.raises(AuthorizationError):
        context_for(runtime_engine, "kara-subject", company)
