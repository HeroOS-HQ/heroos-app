"""Founder self-registration end to end on PostgreSQL (M1-10C).

The production application (``create_app``, staging settings, self-registration
enabled) with Cognito-shaped access tokens verified by the production provider.
Every request runs as the disposable RLS-restricted runtime role; the only
identity-creating capability it has is ``heroos_register_company``. Ground truth
is read as the migration owner.
"""

import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.models import VerifiedIdentity
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.companies.registration import register_founder_company
from app.core.config import Settings
from app.db.session import get_db
from app.identity import service
from app.identity.operator import set_actor_reference
from app.main import create_app
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, LocalJWKClient
from tests.tenant_isolation.conftest import (
    OIDC_TEST_ISSUER,
    TEST_REFERENCE,
    TenantDatabase,
    Tenants,
)

KID = "founder-registration-key"
FORBIDDEN = (403, {"detail": "Forbidden"})
URL = "/company-registrations"
REGISTRATION_REFERENCE = r"^registration:[0-9a-f-]{36}$"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def auth(signing_key: rsa.RSAPrivateKey) -> Callable[[str], dict[str, str]]:
    def _auth(subject: str) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": subject,
            "iss": TEST_COGNITO_ISSUER,
            "client_id": TEST_APP_CLIENT_ID,
            "token_use": "access",
            "iat": now,
            "exp": now + 600,
            # Never used for anything: no email or claim establishes ownership.
            "email": "ceo@existing-company.test",
            "email_verified": True,
        }
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID})
        return {"Authorization": f"Bearer {token}"}

    return _auth


@pytest.fixture
def http_sessions(tenant_database: TenantDatabase) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        tenant_database.runtime_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _client(
    sessions: sessionmaker[Session], signing_key: rsa.RSAPrivateKey, *, enabled: bool
) -> TestClient:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    provider = CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=LocalJWKClient({"keys": [jwk]}),
    )
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
        heroos_self_registration_enabled=enabled,
    )
    app = create_app(settings)

    def _db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client(
    http_sessions: sessionmaker[Session], signing_key: rsa.RSAPrivateKey, tenants: Tenants
) -> TestClient:
    return _client(http_sessions, signing_key, enabled=True)


def scalar(admin_engine: Engine, sql: str, **params: object) -> Any:
    with admin_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(admin_engine: Engine, sql: str, **params: object) -> list[tuple[Any, ...]]:
    with admin_engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql), params)]


def table_counts(admin_engine: Engine) -> dict[str, int]:
    return {
        table: scalar(admin_engine, f"SELECT count(*) FROM {table}")
        for table in (
            "users",
            "user_identities",
            "companies",
            "company_blueprints",
            "memberships",
            "company_registrations",
            "identity_events",
            "membership_events",
            "company_events",
        )
    }


def operator_change(operator_engine: Engine, change: Callable[[Session], object]) -> None:
    with Session(operator_engine, autoflush=False) as session:
        set_actor_reference(session, TEST_REFERENCE)
        change(session)
        session.commit()


# --- a new founder --------------------------------------------------------------------


def test_new_founder_gets_a_company_workspace_as_its_administrator(
    client: TestClient,
    admin_engine: Engine,
    tenant_database: TenantDatabase,
    tenants: Tenants,
    auth: Any,
) -> None:
    founder = auth("founder-one-subject")
    # Before registration HeroOS does not know the identity at all.
    assert (client.get("/me/companies", headers=founder).status_code) == 403

    response = client.post(URL, headers=founder, json={"company_name": "Founder One Ltd"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"outcome", "company_id", "membership_id", "role"}
    assert (body["outcome"], body["role"]) == ("created", "company_admin")
    company = uuid.UUID(body["company_id"])
    assert company not in (tenants.a.company, tenants.b.company)

    # The binding is the verified (issuer, subject); never the email claim.
    ((user, issuer, identity_status, user_status),) = rows(
        admin_engine,
        "SELECT u.id, i.issuer, i.status, u.status FROM user_identities i "
        "JOIN users u ON u.id = i.user_id WHERE i.subject = 'founder-one-subject'",
    )
    assert (issuer, identity_status, user_status) == (TEST_COGNITO_ISSUER, "active", "active")
    assert rows(
        admin_engine,
        "SELECT c.name, m.user_id, m.role, m.status, b.licensing_location, "
        "b.employment_jurisdiction FROM companies c "
        "JOIN memberships m ON m.company_id = c.id "
        "JOIN company_blueprints b ON b.company_id = c.id WHERE c.id = :c",
        c=company,
    ) == [("Founder One Ltd", user, "company_admin", "active", None, None)]

    # Audited as the API login, attributed to this registration, one transaction.
    ((registration,),) = rows(
        admin_engine, "SELECT id FROM company_registrations WHERE company_id = :c", c=company
    )
    events = rows(
        admin_engine,
        "SELECT 'identity', event_type, actor_kind, db_role, actor_reference, txid "
        "FROM identity_events WHERE user_id = :u UNION ALL "
        "SELECT 'membership', event_type, actor_kind, db_role, actor_reference, txid "
        "FROM membership_events WHERE company_id = :c UNION ALL "
        "SELECT 'company', event_type, actor_kind, db_role, actor_reference, txid "
        "FROM company_events WHERE company_id = :c",
        u=user,
        c=company,
    )
    assert sorted((e[0], e[1]) for e in events) == [
        ("company", "company_registered"),
        ("identity", "identity_bound"),
        ("identity", "user_created"),
        ("membership", "membership_granted"),
    ]
    assert {(e[2], e[3], e[4]) for e in events} == {
        ("api", tenant_database.runtime_role, f"registration:{registration}")
    }
    assert len({e[5] for e in events}) == 1

    # The workspace is usable at once, with administrator rights, and nothing else.
    base = f"/companies/{company}"
    assert client.get(base, headers=founder).json() == {
        "id": str(company),
        "name": "Founder One Ltd",
    }
    assert client.get(f"{base}/membership", headers=founder).json()["role"] == "company_admin"
    assert (
        client.patch(
            f"{base}/blueprint", headers=founder, json={"licensing": {"location": "difc"}}
        ).status_code
        == 200
    )
    assert client.get("/me/companies", headers=founder).json() == [
        {
            "company_id": str(company),
            "name": "Founder One Ltd",
            "membership_id": body["membership_id"],
            "role": "company_admin",
        }
    ]
    for other in (tenants.a.company, tenants.b.company):
        for path in (f"/companies/{other}", f"/companies/{other}/blueprint"):
            assert (client.get(path, headers=founder).status_code) == 403


def test_open_registration_keeps_uninvited_founders_apart_and_returns_their_own_workspace(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    # Open sign-up: two people HeroOS has never seen, no invitation, the same
    # Company name and the same email claim (neither is proof of ownership).
    one, two = auth("open-founder-one"), auth("open-founder-two")
    first = client.post(URL, headers=one, json={"company_name": "Same Name LLC"})
    second = client.post(URL, headers=two, json={"company_name": "Same Name LLC"})

    assert (first.status_code, second.status_code) == (201, 201)
    mine, theirs = uuid.UUID(first.json()["company_id"]), uuid.UUID(second.json()["company_id"])
    assert len({mine, theirs, tenants.a.company, tenants.b.company}) == 4
    for headers, own, other in ((one, mine, theirs), (two, theirs, mine)):
        # Each administers exactly the Company they created...
        assert [
            (c["company_id"], c["role"])
            for c in client.get("/me/companies", headers=headers).json()
        ] == [(str(own), "company_admin")]
        # ...and cannot read or change the other one, or any existing Company.
        for company in (other, tenants.a.company, tenants.b.company):
            for path in (f"/companies/{company}", f"/companies/{company}/membership"):
                response = client.get(path, headers=headers)
                assert (response.status_code, response.json()) == FORBIDDEN
            response = client.patch(
                f"/companies/{company}/blueprint", headers=headers, json={"legal_name": "Mine"}
            )
            assert (response.status_code, response.json()) == FORBIDDEN

    # A returning founder (a later sign-in, a refresh, a callback retry) gets
    # the same workspace back: no second Company, no second Membership.
    before = table_counts(admin_engine)
    again = client.post(URL, headers=one, json={"company_name": "Another Name LLC"})
    assert (again.status_code, again.json()) == (200, {**first.json(), "outcome": "existing"})
    assert table_counts(admin_engine) == before
    assert [
        (str(user), role)
        for user, role in rows(
            admin_engine,
            "SELECT user_id, role FROM memberships WHERE company_id = :c",
            c=mine,
        )
    ] == [
        (
            str(
                scalar(
                    admin_engine,
                    "SELECT user_id FROM user_identities WHERE subject = :s",
                    s="open-founder-one",
                )
            ),
            "company_admin",
        )
    ]

    # Operator-provisioned members of the existing Companies are unaffected.
    for subject, company in (
        ("alice-subject", tenants.a.company),
        ("bob-subject", tenants.b.company),
    ):
        assert [
            (c["company_id"], c["role"])
            for c in client.get("/me/companies", headers=auth(subject)).json()
        ] == [(str(company), "member")]


def test_registration_answers_are_stored_atomically_and_stay_unconfirmed(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    response = client.post(
        URL,
        headers=auth("founder-two-subject"),
        json={
            "company_name": "Founder Two FZ-LLC",
            "blueprint": {
                "legal_name": "Founder Two FZ-LLC",
                "employee_count": 8,
                "licensing": {"location": "other", "authority": "Jebel Ali Free Zone Authority"},
            },
        },
    )
    assert response.status_code == 201
    company = uuid.UUID(response.json()["company_id"])
    assert rows(
        admin_engine,
        "SELECT legal_name, employee_count, licensing_location, licensing_authority, "
        "employment_jurisdiction FROM company_blueprints WHERE company_id = :c",
        c=company,
    ) == [("Founder Two FZ-LLC", 8, "other", "Jebel Ali Free Zone Authority", None)]
    jurisdiction = client.get(
        f"/companies/{company}/blueprint", headers=auth("founder-two-subject")
    ).json()["jurisdiction"]
    # "Other" never becomes UAE Federal / MOHRE by itself.
    assert (jurisdiction["readiness"], jurisdiction["guidance_allowed"]) == ("unconfirmed", False)


def test_a_failed_initial_blueprint_leaves_no_registration_behind(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any, monkeypatch: Any
) -> None:
    before = table_counts(admin_engine)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure after the registration function")

    monkeypatch.setattr("app.api.onboarding.update_company_blueprint", fail)
    failing = TestClient(client.app, raise_server_exceptions=False)
    response = failing.post(
        URL,
        headers=auth("founder-three-subject"),
        json={"company_name": "Doomed Ltd", "blueprint": {"legal_name": "Doomed Ltd"}},
    )

    assert response.status_code == 500
    assert table_counts(admin_engine) == before


# --- retries, concurrency, existing identities ------------------------------------


def test_retries_return_the_same_company_and_create_nothing(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    founder = auth("retry-founder-subject")
    first = client.post(URL, headers=founder, json={"company_name": "Retry Ltd"})
    assert first.status_code == 201
    before = table_counts(admin_engine)

    for body in (
        {"company_name": "Retry Ltd"},
        # A second, different submission (or a double-click with edits) does
        # not create a second Company, and its answers are not applied.
        {"company_name": "Another Ltd", "blueprint": {"legal_name": "Another Ltd"}},
    ):
        again = client.post(URL, headers=founder, json=body)
        assert again.status_code == 200
        assert again.json() == {**first.json(), "outcome": "existing"}
    assert table_counts(admin_engine) == before
    assert (
        scalar(
            admin_engine,
            "SELECT legal_name FROM company_blueprints WHERE company_id = :c",
            c=uuid.UUID(first.json()["company_id"]),
        )
        is None
    )


def test_a_demoted_founder_retrying_registration_is_told_the_role_actually_held(
    client: TestClient, admin_engine: Engine, operator_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    # M1-10E: the answer used to re-assert company_admin for every earlier
    # registration, even after an operator had demoted the founder.
    founder = auth("demoted-founder-subject")
    first = client.post(URL, headers=founder, json={"company_name": "Demoted Ltd"}).json()
    company = uuid.UUID(first["company_id"])
    membership = uuid.UUID(first["membership_id"])
    operator_change(
        operator_engine,
        lambda session: service.set_membership_role(
            session, company_id=company, membership_id=membership, role="member"
        ),
    )
    before = table_counts(admin_engine)

    again = client.post(URL, headers=founder, json={"company_name": "Demoted Ltd"})

    assert again.status_code == 200
    assert again.json() == {**first, "outcome": "existing", "role": "member"}
    membership_view = client.get(f"/companies/{company}/membership", headers=founder).json()
    assert membership_view["role"] == "member"
    # Nothing was granted or created by asking again.
    assert table_counts(admin_engine) == before
    assert (
        client.patch(
            f"/companies/{company}/blueprint", headers=founder, json={"industry": "x"}
        ).status_code
        == 403
    )


def _wait_for_lock_wait(admin_engine: Engine, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    with admin_engine.connect() as conn:
        while time.monotonic() < deadline:
            if conn.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock'"
                )
            ):
                return
            conn.rollback()
            time.sleep(0.05)
    raise AssertionError("the concurrent registration never waited")


def test_concurrent_submissions_create_exactly_one_company(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    identity = VerifiedIdentity(subject="racing-founder-subject", issuer=TEST_COGNITO_ISSUER)
    before = table_counts(admin_engine)
    second: list[object] = []

    def submit_again() -> None:
        with Session(runtime_engine, autoflush=False) as session:
            result = register_founder_company(session, identity, "Racing Ltd (second tab)")
            session.commit()
            second.append(result)

    with Session(runtime_engine, autoflush=False) as session:
        first = register_founder_company(session, identity, "Racing Ltd")
        thread = threading.Thread(target=submit_again)
        thread.start()
        # The second submission waits on the first one's registration lock.
        _wait_for_lock_wait(admin_engine)
        session.commit()
    thread.join(timeout=30)

    assert first.created
    (result,) = second
    assert (result.outcome, result.company_id, result.membership_id) == (  # type: ignore[attr-defined]
        "existing",
        first.company_id,
        first.membership_id,
    )
    after = table_counts(admin_engine)
    assert {table: after[table] - before[table] for table in after} == {
        "users": 1,
        "user_identities": 1,
        "companies": 1,
        "company_blueprints": 1,
        "memberships": 1,
        "company_registrations": 1,
        "identity_events": 2,
        "membership_events": 1,
        "company_events": 1,
    }


def test_another_binding_of_the_same_person_returns_the_same_company(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    # alice holds bindings under several issuers (as during the M5 move from
    # Auth0 to Cognito): one person, one self-service registration.
    results = []
    for issuer, name in ((TEST_COGNITO_ISSUER, "Alice Ventures"), (OIDC_TEST_ISSUER, "Alice Two")):
        with Session(runtime_engine, autoflush=False) as session:
            identity = VerifiedIdentity(subject="alice-subject", issuer=issuer)
            results.append(register_founder_company(session, identity, name))
            session.commit()

    first, second = results
    assert (first.outcome, second.outcome) == ("created", "existing")
    assert (second.company_id, second.membership_id) == (first.company_id, first.membership_id)
    # The answer names the binding used now, not the one that registered.
    assert second.identity_id != first.identity_id
    assert (
        scalar(
            admin_engine,
            "SELECT count(*) FROM company_registrations WHERE user_id = :u",
            u=tenants.a.user,
        )
        == 1
    )
    assert scalar(admin_engine, "SELECT count(*) FROM companies WHERE name = 'Alice Two'") == 0


def test_an_existing_member_registers_a_new_company_without_gaining_anything_else(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    alice = auth("alice-subject")
    response = client.post(URL, headers=alice, json={"company_name": "Company A"})

    assert response.status_code == 201
    new = uuid.UUID(response.json()["company_id"])
    # Same name as an existing Company: still a new, separate Company.
    assert new != tenants.a.company
    assert scalar(admin_engine, "SELECT count(*) FROM companies WHERE name = 'Company A'") == 2
    # The existing User is reused (no second person), and stays a member of A.
    assert (
        scalar(admin_engine, "SELECT user_id FROM memberships WHERE company_id = :c", c=new)
        == tenants.a.user
    )
    assert (
        scalar(admin_engine, "SELECT count(*) FROM user_identities WHERE subject = 'alice-subject'")
        == 4
    )
    assert (
        client.get(f"/companies/{tenants.a.company}/membership", headers=alice).json()["role"]
        == "member"
    )
    assert (
        client.patch(
            f"/companies/{tenants.a.company}/blueprint", headers=alice, json={"legal_name": "Mine"}
        ).json()
        == FORBIDDEN[1]
    )
    assert [
        (c["company_id"], c["role"]) for c in client.get("/me/companies", headers=alice).json()
    ] == sorted(
        [(str(tenants.a.company), "member"), (str(new), "company_admin")],
        key=lambda item: ("Company A", item[0]),
    )
    # Nobody else gains access to the new Company.
    for subject in ("bob-subject", "carol-subject"):
        response = client.get(f"/companies/{new}", headers=auth(subject))
        assert (response.status_code, response.json()) == FORBIDDEN


@pytest.mark.parametrize("change", ["user-suspended", "identity-revoked"])
def test_inactive_identities_cannot_register(
    client: TestClient,
    admin_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,
    change: str,
) -> None:
    def deactivate(session: Session) -> None:
        if change == "user-suspended":
            service.suspend_user(session, user_id=tenants.a.user)
        else:
            identity = session.scalar(
                text("SELECT id FROM user_identities WHERE user_id = :u AND issuer = :i"),
                {"u": tenants.a.user, "i": TEST_COGNITO_ISSUER},
            )
            service.revoke_identity(session, identity_id=identity)

    operator_change(operator_engine, deactivate)
    before = table_counts(admin_engine)

    response = client.post(URL, headers=auth("alice-subject"), json={"company_name": "Escape"})

    assert (response.status_code, response.json()) == FORBIDDEN
    assert table_counts(admin_engine) == before
    assert client.get("/me/companies", headers=auth("alice-subject")).status_code == 403


@pytest.mark.parametrize("change", ["membership-revoked", "user-suspended"])
def test_a_revoked_founder_does_not_get_the_workspace_back_by_registering_again(
    client: TestClient,
    admin_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,
    change: str,
) -> None:
    founder = auth("revoked-founder-subject")
    created = client.post(URL, headers=founder, json={"company_name": "Revoked Ltd"}).json()
    company = uuid.UUID(created["company_id"])
    membership = uuid.UUID(created["membership_id"])
    user = scalar(admin_engine, "SELECT user_id FROM memberships WHERE id = :m", m=membership)

    def deactivate(session: Session) -> None:
        if change == "membership-revoked":
            service.revoke_membership(session, company_id=company, membership_id=membership)
        else:
            service.suspend_user(session, user_id=user)

    operator_change(operator_engine, deactivate)
    before = table_counts(admin_engine)

    for response in (
        client.post(URL, headers=founder, json={"company_name": "Revoked Ltd"}),
        client.get(f"/companies/{company}", headers=founder),
        client.patch(f"/companies/{company}/blueprint", headers=founder, json={"industry": "x"}),
    ):
        assert (response.status_code, response.json()) == FORBIDDEN
    assert table_counts(admin_engine) == before


# --- unprovisioned identities and the activation switch ---------------------------


def test_unprovisioned_identities_reach_nothing_but_registration(
    client: TestClient, tenants: Tenants, auth: Any
) -> None:
    stranger = auth("never-registered-subject")
    a = tenants.a
    for method, path in (
        ("GET", f"/companies/{a.company}"),
        ("GET", f"/companies/{a.company}/membership"),
        ("GET", f"/companies/{a.company}/blueprint"),
        ("PATCH", f"/companies/{a.company}/blueprint"),
        ("GET", f"/companies/{a.company}/cases"),
        ("GET", f"/companies/{a.company}/cases/{a.case}"),
        ("GET", "/me/companies"),
    ):
        response = client.request(method, path, headers=stranger, json={"legal_name": "x"})
        assert (response.status_code, response.json()) == FORBIDDEN, (method, path)


def test_registration_is_refused_while_disabled(
    http_sessions: sessionmaker[Session],
    signing_key: rsa.RSAPrivateKey,
    admin_engine: Engine,
    tenants: Tenants,
    auth: Any,
) -> None:
    disabled = _client(http_sessions, signing_key, enabled=False)
    before = table_counts(admin_engine)
    response = disabled.post(URL, headers=auth("early-founder-subject"), json={"company_name": "x"})
    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})
    assert table_counts(admin_engine) == before


# --- the database capability itself ------------------------------------------------


@pytest.mark.parametrize(
    ("issuer", "subject", "name", "sqlstate"),
    [
        ("http://idp.test/", "s", "Acme", "42501"),
        ("https://idp.test/?q=1", "s", "Acme", "42501"),
        ("https://idp.test/' OR '1'='1", "s", "Acme", "42501"),
        ("https://idp.test/a\\b", "s", "Acme", "42501"),
        ("a@example.com", "s", "Acme", "42501"),
        (TEST_COGNITO_ISSUER, "", "Acme", "42501"),
        (TEST_COGNITO_ISSUER, " padded", "Acme", "42501"),
        (TEST_COGNITO_ISSUER, "line\nbreak", "Acme", "42501"),
        (TEST_COGNITO_ISSUER, "x" * 256, "Acme", "42501"),
        (TEST_COGNITO_ISSUER, "s", "", "22023"),
        (TEST_COGNITO_ISSUER, "s", " Acme", "22023"),
        (TEST_COGNITO_ISSUER, "s", "Acme\tLtd", "22023"),
        (TEST_COGNITO_ISSUER, "s", "x" * 201, "22023"),
    ],
)
def test_the_function_revalidates_its_inputs(
    runtime_engine: Engine,
    admin_engine: Engine,
    tenants: Tenants,
    issuer: str,
    subject: str,
    name: str,
    sqlstate: str,
) -> None:
    before = table_counts(admin_engine)
    with runtime_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(
            text("SELECT * FROM heroos_register_company(:i, :s, :n)"),
            {"i": issuer, "s": subject, "n": name},
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == sqlstate
    assert table_counts(admin_engine) == before


def test_only_the_api_role_may_call_the_registration_capability(
    operator_engine: Engine, admin_engine: Engine, tenant_database: TenantDatabase, tenants: Tenants
) -> None:
    with operator_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(
            text("SELECT * FROM heroos_register_company(:i, 'op-subject', 'Operator Ltd')"),
            {"i": TEST_COGNITO_ISSUER},
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"

    acl = rows(
        admin_engine,
        "SELECT p.proname, p.prosecdef, p.proconfig, "
        "has_function_privilege(:runtime, p.oid, 'EXECUTE'), "
        "has_function_privilege(:operator, p.oid, 'EXECUTE'), "
        "has_function_privilege('public', p.oid, 'EXECUTE') "
        "FROM pg_proc p WHERE p.proname IN ('heroos_register_company', "
        "'heroos_identity_companies') ORDER BY p.proname",
        runtime=tenant_database.runtime_role,
        operator=tenant_database.operator_role,
    )
    assert acl == [
        ("heroos_identity_companies", True, ['search_path=""'], True, False, False),
        ("heroos_register_company", True, ['search_path=""'], True, False, False),
    ]


def test_registration_references_cannot_be_borrowed(
    operator_engine: Engine, runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    reference = f"registration:{uuid.uuid4()}"
    # The operator cannot pass its changes off as a self-service registration ...
    with operator_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": reference}
        )
        conn.execute(
            text("UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :u"),
            {"u": tenants.a.user},
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "22023"
    # ... and the API role still cannot write identities or Memberships directly,
    # whatever reference it sets.
    with runtime_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": reference}
        )
        conn.execute(
            text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(tenants.a.company)}
        )
        conn.execute(
            text("UPDATE memberships SET role = 'company_admin' WHERE id = :m"),
            {"m": tenants.a.membership},
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"
    assert scalar(admin_engine, "SELECT status FROM users WHERE id = :u", u=tenants.a.user) == (
        "active"
    )


def test_registration_records_are_append_only(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    client.post(URL, headers=auth("ledger-founder-subject"), json={"company_name": "Ledger Ltd"})
    for statement in (
        "UPDATE company_registrations SET registered_at = now()",
        "DELETE FROM company_registrations",
        "TRUNCATE company_registrations",
    ):
        with admin_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
            conn.execute(text(statement))
        assert "append-only" in str(exc_info.value.orig)


def test_workspace_discovery_lists_only_the_callers_active_memberships(
    client: TestClient, operator_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    assert [
        c["company_id"] for c in client.get("/me/companies", headers=auth("bob-subject")).json()
    ] == [str(tenants.b.company)]
    operator_change(
        operator_engine,
        lambda session: service.revoke_membership(
            session, company_id=tenants.b.company, membership_id=tenants.b.membership
        ),
    )
    assert client.get("/me/companies", headers=auth("bob-subject")).json() == []
