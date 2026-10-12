"""The shipped Company endpoints on PostgreSQL with RLS, authenticated by the OIDC provider.

Same application (``create_app``, staging) and runtime-role database as
test_api_routes.py, but bearer tokens are RFC 9068 access tokens verified by
``OidcAccessTokenProvider`` (discovery stubbed, keys generated in-process).
Authorization and tenant isolation must not depend on which provider issued
the token.
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
from app.auth.providers.oidc import OidcAccessTokenProvider, OidcKeySource
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import LocalJWKClient
from tests.tenant_isolation.conftest import (
    OIDC_TEST_ISSUER,
    TenantDatabase,
    Tenants,
    tenant_setting,
)

ISSUER = OIDC_TEST_ISSUER
AUDIENCE = "https://api.heroos-demo.test.invalid"
CLIENT_ID = "web-client-123"
KID = "tenant-isolation-oidc-key"
FORBIDDEN = (403, {"detail": "Forbidden"})
NOT_FOUND = (404, {"detail": "Not found"})


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def provider(signing_key: rsa.RSAPrivateKey) -> OidcAccessTokenProvider:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    keys = OidcKeySource(
        ISSUER,
        fetch=lambda _url: {
            "issuer": ISSUER,
            "jwks_uri": "https://heroos-demo.idp.test.invalid/jwks",
        },
        client_factory=lambda _uri: LocalJWKClient({"keys": [jwk]}),
    )
    return OidcAccessTokenProvider(
        issuer=ISSUER, audience=AUDIENCE, keys=keys, client_ids=[CLIENT_ID]
    )


@pytest.fixture
def auth(signing_key: rsa.RSAPrivateKey) -> Any:
    def _auth(subject: str, typ: str = "at+jwt", **overrides: Any) -> dict[str, str]:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": subject,
            "aud": AUDIENCE,
            "client_id": CLIENT_ID,
            "iat": now,
            "exp": now + 600,
            "jti": str(uuid.uuid4()),
            **overrides,
        }
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KID, "typ": typ})
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
    http_sessions: sessionmaker[Session], provider: OidcAccessTokenProvider, tenants: Tenants
) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="oidc",
        heroos_oidc_issuer=ISSUER,
        heroos_oidc_audience=AUDIENCE,
        heroos_oidc_client_ids=CLIENT_ID,
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
    for subject, tenant in (("alice-subject", tenants.a), ("bob-subject", tenants.b)):
        base = f"/companies/{tenant.company}"
        assert client.get(base, headers=auth(subject)).json()["id"] == str(tenant.company)
        listed = client.get(f"{base}/cases", headers=auth(subject)).json()
        assert [c["id"] for c in listed] == [str(tenant.case)]


def test_cross_company_access_is_denied(client: TestClient, tenants: Tenants, auth: Any) -> None:
    a, b = tenants.a, tenants.b
    for path in (
        f"/companies/{b.company}",
        f"/companies/{b.company}/cases",
        f"/companies/{uuid.uuid4()}/cases",
    ):
        response = client.get(path, headers=auth("alice-subject"))
        assert (response.status_code, response.json()) == FORBIDDEN
    guessed = client.get(f"/companies/{a.company}/cases/{b.case}", headers=auth("alice-subject"))
    assert (guessed.status_code, guessed.json()) == NOT_FOUND


def test_id_tokens_and_wrong_audience_are_unauthenticated(
    client: TestClient, tenants: Tenants, auth: Any
) -> None:
    url = f"/companies/{tenants.a.company}/cases"
    assert client.get(url).status_code == 401
    id_token = auth("alice-subject", typ="JWT", aud=CLIENT_ID, nonce="n", client_id=None)
    assert client.get(url, headers=id_token).status_code == 401
    assert (
        client.get(url, headers=auth("alice-subject", aud="https://other.test.invalid")).status_code
        == 401
    )
    for subject in ("stranger", "carol-subject"):
        response = client.get(url, headers=auth(subject))
        assert (response.status_code, response.json()) == FORBIDDEN


def test_no_tenant_context_survives_on_the_pooled_connection(
    client: TestClient, http_sessions: sessionmaker[Session], tenants: Tenants, auth: Any
) -> None:
    for subject, tenant in (("alice-subject", tenants.a), ("bob-subject", tenants.b)):
        listed = client.get(f"/companies/{tenant.company}/cases", headers=auth(subject)).json()
        assert {c["company_id"] for c in listed} == {str(tenant.company)}
        with http_sessions() as db:
            assert tenant_setting(db) in (None, "")
