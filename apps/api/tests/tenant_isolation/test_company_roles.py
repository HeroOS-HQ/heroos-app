"""Company administrator authorization end to end on PostgreSQL (M1-10C).

The production application (``create_app``, staging settings) with Cognito-shaped
access tokens verified by the production provider; every database access runs as
the disposable RLS-restricted runtime role on one pooled connection. Roles are
assigned the trusted way (identity-operator role, ``app.identity.service``).
"""

import time
import uuid
from collections.abc import Generator, Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.session import get_db
from app.identity import service
from app.identity.operator import set_actor_reference
from app.main import create_app
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, LocalJWKClient
from tests.tenant_isolation.conftest import TEST_REFERENCE, TenantDatabase, Tenants, tenant_setting

KID = "company-roles-cognito-key"
FORBIDDEN = (403, {"detail": "Forbidden"})


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def auth(signing_key: rsa.RSAPrivateKey) -> Any:
    def _auth(subject: str) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": subject,
            "iss": TEST_COGNITO_ISSUER,
            "client_id": TEST_APP_CLIENT_ID,
            "token_use": "access",
            "iat": now,
            "exp": now + 600,
            # Claims never grant a role: only the Membership row does.
            "custom:role": "company_admin",
            "cognito:groups": ["admin", "company_admin"],
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


@pytest.fixture
def client(
    http_sessions: sessionmaker[Session], signing_key: rsa.RSAPrivateKey, tenants: Tenants
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
    )
    app = create_app(settings)

    def _db() -> Generator[Session, None, None]:
        with http_sessions() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def set_role(operator_engine: Engine, company: uuid.UUID, membership: uuid.UUID, role: str) -> None:
    with Session(operator_engine, autoflush=False) as session:
        set_actor_reference(session, TEST_REFERENCE)
        service.set_membership_role(
            session, company_id=company, membership_id=membership, role=role
        )
        session.commit()


def blueprint_row(admin_engine: Engine, company: uuid.UUID) -> tuple[Any, ...]:
    with admin_engine.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    "SELECT legal_name, industry, employee_count, licensing_location, "
                    "licensing_authority, primary_jurisdiction, employment_jurisdiction, "
                    "confirmed_licensing_location, jurisdiction_confirmed_at "
                    "FROM company_blueprints WHERE company_id = :c"
                ),
                {"c": company},
            ).one()
        )


@pytest.fixture
def alice_admin(operator_engine: Engine, tenants: Tenants) -> None:
    set_role(operator_engine, tenants.a.company, tenants.a.membership, "company_admin")


def test_administrator_reads_and_updates_own_blueprint(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any, alice_admin: None
) -> None:
    base = f"/companies/{tenants.a.company}"
    membership = client.get(f"{base}/membership", headers=auth("alice-subject"))
    assert membership.json() == {
        "company_id": str(tenants.a.company),
        "membership_id": str(tenants.a.membership),
        "role": "company_admin",
        "can_update_blueprint": True,
    }

    response = client.patch(
        f"{base}/blueprint",
        headers=auth("alice-subject"),
        json={
            "legal_name": "Alpha Holdings Ltd",
            "industry": "Hospitality",
            "employee_count": 40,
            "licensing": {"location": "difc"},
        },
    )
    assert response.status_code == 200
    assert response.json()["jurisdiction"] == {
        "readiness": "unconfirmed",
        "reason": "awaiting_confirmation",
        "employment_jurisdiction": None,
        "confirmed_at": None,
        "guidance_allowed": False,
    }
    # Persisted as the runtime role, and the legacy label is untouched.
    assert blueprint_row(admin_engine, tenants.a.company) == (
        "Alpha Holdings Ltd",
        "Hospitality",
        40,
        "difc",
        None,
        "DIFC",
        None,
        None,
        None,
    )
    assert client.get(f"{base}/blueprint", headers=auth("alice-subject")).json() == response.json()


def test_members_read_but_cannot_update_the_blueprint(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    # Existing Members were not made administrators by the migration.
    before = blueprint_row(admin_engine, tenants.a.company)
    base = f"/companies/{tenants.a.company}"

    membership = client.get(f"{base}/membership", headers=auth("alice-subject")).json()
    assert (membership["role"], membership["can_update_blueprint"]) == ("member", False)
    read = client.get(f"{base}/blueprint", headers=auth("alice-subject"))
    assert read.status_code == 200
    assert read.json()["legal_name"] == "Company A LLC"

    for body in (
        {"legal_name": "Hijacked"},
        {"licensing": {"location": "difc"}},
        {},
    ):
        response = client.patch(f"{base}/blueprint", headers=auth("alice-subject"), json=body)
        assert (response.status_code, response.json()) == FORBIDDEN
    assert blueprint_row(admin_engine, tenants.a.company) == before


def test_no_one_can_promote_themselves_through_the_api(
    client: TestClient, admin_engine: Engine, tenants: Tenants, auth: Any
) -> None:
    base = f"/companies/{tenants.a.company}"
    # Token claims ("custom:role", groups) are ignored; there is no role route,
    # and role fields in a body are refused even for an administrator.
    attempts = [
        client.patch(
            f"{base}/blueprint", headers=auth("alice-subject"), json={"role": "company_admin"}
        ),
        client.post(
            f"{base}/membership", headers=auth("alice-subject"), json={"role": "company_admin"}
        ),
        client.put(
            f"{base}/membership", headers=auth("alice-subject"), json={"role": "company_admin"}
        ),
        client.patch(
            f"{base}/membership", headers=auth("alice-subject"), json={"role": "company_admin"}
        ),
        client.post("/companies", headers=auth("alice-subject"), json={"name": "Mine"}),
        client.post(
            f"{base}/members", headers=auth("alice-subject"), json={"role": "company_admin"}
        ),
    ]
    assert [r.status_code for r in attempts] == [403, 405, 405, 405, 404, 404]
    with admin_engine.connect() as conn:
        assert set(conn.scalars(text("SELECT role FROM memberships"))) == {"member"}
        assert conn.scalar(text("SELECT count(*) FROM companies")) == 2


def test_administrator_of_one_company_has_no_power_in_another(
    client: TestClient,
    admin_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,
    alice_admin: None,
) -> None:
    before = blueprint_row(admin_engine, tenants.b.company)
    for company in (tenants.b.company, uuid.uuid4()):
        base = f"/companies/{company}"
        for response in (
            client.get(f"{base}/blueprint", headers=auth("alice-subject")),
            client.get(f"{base}/membership", headers=auth("alice-subject")),
            client.patch(
                f"{base}/blueprint", headers=auth("alice-subject"), json={"legal_name": "Mine"}
            ),
        ):
            assert (response.status_code, response.json()) == FORBIDDEN

    # Even as a member of B, alice's administrator role in A gives nothing in B.
    with Session(operator_engine, autoflush=False) as session:
        set_actor_reference(session, TEST_REFERENCE)
        service.grant_membership(
            session,
            company_id=tenants.b.company,
            issuer="urn:heroos:test",
            subject="alice-subject",
        )
        session.commit()
    base = f"/companies/{tenants.b.company}"
    assert (
        client.get(f"{base}/membership", headers=auth("alice-subject")).json()["role"] == "member"
    )
    response = client.patch(
        f"{base}/blueprint", headers=auth("alice-subject"), json={"legal_name": "Mine"}
    )
    assert (response.status_code, response.json()) == FORBIDDEN
    assert blueprint_row(admin_engine, tenants.b.company) == before


@pytest.mark.parametrize(
    "change", ["demoted", "membership-revoked", "user-suspended", "identity-revoked"]
)
def test_administrator_access_ends_on_the_next_request(
    client: TestClient,
    admin_engine: Engine,
    operator_engine: Engine,
    tenants: Tenants,
    auth: Any,
    alice_admin: None,
    change: str,
) -> None:
    url = f"/companies/{tenants.a.company}/blueprint"
    assert (
        client.patch(url, headers=auth("alice-subject"), json={"industry": "Before"}).status_code
        == 200
    )

    with Session(operator_engine, autoflush=False) as session:
        set_actor_reference(session, TEST_REFERENCE)
        if change == "demoted":
            service.set_membership_role(
                session,
                company_id=tenants.a.company,
                membership_id=tenants.a.membership,
                role="member",
            )
        elif change == "membership-revoked":
            service.revoke_membership(
                session, company_id=tenants.a.company, membership_id=tenants.a.membership
            )
        elif change == "user-suspended":
            service.suspend_user(session, user_id=tenants.a.user)
        else:
            # The Cognito binding (the one the token uses).
            identity = session.scalar(
                text("SELECT id FROM user_identities WHERE user_id = :u AND issuer = :i"),
                {"u": tenants.a.user, "i": TEST_COGNITO_ISSUER},
            )
            service.revoke_identity(session, identity_id=identity)
        session.commit()

    response = client.patch(url, headers=auth("alice-subject"), json={"industry": "After"})
    assert (response.status_code, response.json()) == FORBIDDEN
    assert blueprint_row(admin_engine, tenants.a.company)[1] == "Before"
    read = client.get(url, headers=auth("alice-subject"))
    assert read.status_code == (200 if change == "demoted" else 403)


def test_no_tenant_context_survives_an_administrator_write(
    client: TestClient,
    http_sessions: sessionmaker[Session],
    tenants: Tenants,
    auth: Any,
    alice_admin: None,
) -> None:
    for subject, company in (
        ("alice-subject", tenants.a.company),
        ("bob-subject", tenants.b.company),
    ):
        client.patch(
            f"/companies/{company}/blueprint", headers=auth(subject), json={"industry": "x"}
        )
        with http_sessions() as db:
            assert tenant_setting(db) in (None, "")
