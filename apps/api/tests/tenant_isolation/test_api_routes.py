"""The shipped Company endpoints on real PostgreSQL with RLS, as the runtime role.

Unlike test_http_isolation.py (test-only routes, development tokens), this mounts
the production application (``create_app`` with staging settings) and
authenticates Cognito-shaped access tokens through the production
``CognitoAccessTokenProvider``, with keys generated in-process. Every database
access runs as the disposable RLS-restricted runtime role on one pooled connection.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import TEST_APP_CLIENT_ID, TEST_COGNITO_ISSUER, LocalJWKClient
from tests.tenant_isolation.conftest import TenantDatabase, Tenants, tenant_setting

KID = "tenant-isolation-cognito-key"
ALICE = "alice-subject"
BOB = "bob-subject"
FORBIDDEN = (403, {"detail": "Forbidden"})
NOT_FOUND = (404, {"detail": "Not found"})


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def provider(signing_key: rsa.RSAPrivateKey) -> CognitoAccessTokenProvider:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=LocalJWKClient({"keys": [jwk]}),
    )


@pytest.fixture
def auth(signing_key: rsa.RSAPrivateKey) -> Any:
    def _auth(subject: str, **overrides: Any) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "sub": subject,
            "iss": TEST_COGNITO_ISSUER,
            "client_id": TEST_APP_CLIENT_ID,
            "token_use": "access",
            "iat": now,
            "exp": now + 600,
            **overrides,
        }
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID})
        return {"Authorization": f"Bearer {token}"}

    return _auth


@pytest.fixture
def http_sessions(tenant_database: TenantDatabase) -> Iterator[sessionmaker[Session]]:
    # One pooled runtime connection shared by every request in a test.
    engine = create_engine(
        tenant_database.runtime_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def client(
    http_sessions: sessionmaker[Session], provider: CognitoAccessTokenProvider, tenants: Tenants
) -> TestClient:
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


def test_members_read_only_their_own_company(
    client: TestClient, tenants: Tenants, auth: Any
) -> None:
    for subject, tenant in ((ALICE, tenants.a), (BOB, tenants.b)):
        base = f"/companies/{tenant.company}"
        company = client.get(base, headers=auth(subject))
        assert (company.status_code, company.json()["id"]) == (200, str(tenant.company))

        listed = client.get(f"{base}/cases", headers=auth(subject))
        assert listed.status_code == 200
        assert [c["id"] for c in listed.json()] == [str(tenant.case)]
        assert {c["company_id"] for c in listed.json()} == {str(tenant.company)}

        case = client.get(f"{base}/cases/{tenant.case}", headers=auth(subject))
        assert (case.status_code, case.json()["subject_id"]) == (200, str(tenant.subject))


def test_other_company_is_forbidden_like_a_missing_one(
    client: TestClient, tenants: Tenants, auth: Any
) -> None:
    b = tenants.b
    for path in (
        f"/companies/{b.company}",
        f"/companies/{b.company}/cases",
        f"/companies/{b.company}/cases/{b.case}",
        f"/companies/{uuid.uuid4()}/cases",
    ):
        response = client.get(path, headers=auth(ALICE))
        assert (response.status_code, response.json()) == FORBIDDEN


def test_guessed_case_ids_look_missing(client: TestClient, tenants: Tenants, auth: Any) -> None:
    for subject, own, other in ((ALICE, tenants.a, tenants.b), (BOB, tenants.b, tenants.a)):
        base = f"/companies/{own.company}/cases"
        guessed = client.get(f"{base}/{other.case}", headers=auth(subject))
        random = client.get(f"{base}/{uuid.uuid4()}", headers=auth(subject))
        assert (guessed.status_code, guessed.json()) == (random.status_code, random.json())
        assert (guessed.status_code, guessed.json()) == NOT_FOUND


def test_unauthenticated_and_unauthorized_identities(
    client: TestClient, tenants: Tenants, auth: Any
) -> None:
    url = f"/companies/{tenants.a.company}/cases"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth(ALICE, token_use="id")).status_code == 401
    assert client.get(url, headers=auth(ALICE, client_id="other-client")).status_code == 401
    for subject in ("stranger", "carol-subject"):
        response = client.get(url, headers=auth(subject))
        assert (response.status_code, response.json()) == FORBIDDEN


def test_no_tenant_context_survives_on_the_pooled_connection(
    client: TestClient, http_sessions: sessionmaker[Session], tenants: Tenants, auth: Any
) -> None:
    for subject, tenant in ((ALICE, tenants.a), (BOB, tenants.b), (ALICE, tenants.a)):
        listed = client.get(f"/companies/{tenant.company}/cases", headers=auth(subject)).json()
        assert {c["company_id"] for c in listed} == {str(tenant.company)}
        with http_sessions() as db:
            assert tenant_setting(db) in (None, "")
