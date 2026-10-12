"""Shared fixtures for authentication and Company authorization tests.

Everything is local: RSA keys and the JWKS are generated in-process, the database
is in-memory SQLite built from the real HeroOS models, and the protected route
exists only in a test application. PostgreSQL behaviour, including Row-Level
Security, is covered by tests/tenant_isolation. No AWS, Cognito or network access.
"""

import time
import uuid
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import CompanyContext, get_authentication_provider
from app.auth.providers.base import AuthenticationProvider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.auth.providers.development import (
    DEVELOPMENT_ISSUER,
    DevelopmentAuthenticationProvider,
)
from app.db.base import Base
from app.db.models import Company, Membership, User, UserIdentity
from app.db.session import get_db

TEST_COGNITO_ISSUER = "https://cognito-idp.test.invalid/test-user-pool"
TEST_APP_CLIENT_ID = "test-app-client-id"
TEST_KID = "test-signing-key"
TEST_DEV_SECRET = SecretStr("test-only-development-secret-0123456789abcdef")

# Sentinel for removing a claim from a generated token.
OMIT: Any = object()


@pytest.fixture(autouse=True)
def _isolate_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's shell configuration out of the auth tests."""
    import os

    for name in list(os.environ):
        if name.startswith("HEROOS_"):
            monkeypatch.delenv(name)


class LocalJWKClient(jwt.PyJWKClient):
    """The production ``PyJWKClient`` serving a local JWKS instead of fetching one.

    Key selection by ``kid`` and caching still run through PyJWT's real code.
    """

    def __init__(self, jwks: dict[str, Any]) -> None:
        super().__init__("https://jwks.test.invalid/.well-known/jwks.json", cache_keys=True)
        self._jwks = jwks
        self.fetch_count = 0

    def fetch_data(self) -> Any:
        self.fetch_count += 1
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(self._jwks)
        return self._jwks


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def untrusted_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update({"kid": TEST_KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


@pytest.fixture
def jwk_client(jwks: dict[str, Any]) -> LocalJWKClient:
    return LocalJWKClient(jwks)


@pytest.fixture
def cognito_provider(jwk_client: LocalJWKClient) -> CognitoAccessTokenProvider:
    return CognitoAccessTokenProvider(
        issuer=TEST_COGNITO_ISSUER,
        app_client_id=TEST_APP_CLIENT_ID,
        jwks_client=jwk_client,
    )


@pytest.fixture
def development_provider() -> DevelopmentAuthenticationProvider:
    return DevelopmentAuthenticationProvider(environment="development", secret=TEST_DEV_SECRET)


CognitoTokenFactory = Callable[..., str]


@pytest.fixture
def make_cognito_token(signing_key: rsa.RSAPrivateKey) -> CognitoTokenFactory:
    """Build a Cognito-shaped access token; keyword overrides replace claims."""

    def _make(
        subject: str = "alice-subject",
        *,
        key: Any = None,
        kid: str | None = TEST_KID,
        algorithm: str = "RS256",
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": subject,
            "iss": TEST_COGNITO_ISSUER,
            "client_id": TEST_APP_CLIENT_ID,
            "token_use": "access",
            "scope": "aws.cognito.signin.user.admin",
            "auth_time": now,
            "iat": now,
            "exp": now + 600,
            "jti": str(uuid.uuid4()),
            "username": subject,
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not OMIT}
        headers = {"kid": kid} if kid is not None else {}
        return jwt.encode(
            claims, key if key is not None else signing_key, algorithm=algorithm, headers=headers
        )

    return _make


@dataclass(frozen=True)
class SeedData:
    """Company A: alice. Company B: bob. carol has a User row but no Membership."""

    company_a: uuid.UUID
    company_b: uuid.UUID
    alice: uuid.UUID
    bob: uuid.UUID
    carol: uuid.UUID
    alice_membership_a: uuid.UUID
    # alice's Cognito binding.
    alice_identity: uuid.UUID


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _postgresql_setting_functions(dbapi_connection: Any, _: Any) -> None:
        # authorize_company sets the PostgreSQL tenant context. SQLite has no RLS,
        # so these are inert stand-ins; tests/tenant_isolation proves the real
        # behaviour on PostgreSQL.
        dbapi_connection.create_function("set_config", 3, lambda _name, value, _local: value)
        dbapi_connection.create_function("current_setting", 2, lambda _name, _missing_ok: None)

    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            User.__table__,
            UserIdentity.__table__,
            Membership.__table__,
        ],
    )
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def seed(session_factory: sessionmaker[Session]) -> SeedData:
    with session_factory() as db:
        company_a = Company(name="Company A")
        company_b = Company(name="Company B")
        alice, bob, carol = User(), User(), User()
        db.add_all([company_a, company_b, alice, bob, carol])
        db.flush()
        # Exact (issuer, subject) bindings. alice and bob can sign in through
        # Cognito or the development provider; carol through Cognito only.
        alice_identity = UserIdentity(
            user_id=alice.id, issuer=TEST_COGNITO_ISSUER, subject="alice-subject"
        )
        db.add_all(
            [
                alice_identity,
                UserIdentity(user_id=alice.id, issuer=DEVELOPMENT_ISSUER, subject="alice-subject"),
                UserIdentity(user_id=bob.id, issuer=TEST_COGNITO_ISSUER, subject="bob-subject"),
                UserIdentity(user_id=bob.id, issuer=DEVELOPMENT_ISSUER, subject="bob-subject"),
                UserIdentity(user_id=carol.id, issuer=TEST_COGNITO_ISSUER, subject="carol-subject"),
            ]
        )
        db.flush()
        alice_membership_a = Membership(company_id=company_a.id, user_id=alice.id)
        db.add_all([alice_membership_a, Membership(company_id=company_b.id, user_id=bob.id)])
        db.commit()
        return SeedData(
            company_a=company_a.id,
            company_b=company_b.id,
            alice=alice.id,
            bob=bob.id,
            carol=carol.id,
            alice_membership_a=alice_membership_a.id,
            alice_identity=alice_identity.id,
        )


ClientFactory = Callable[[AuthenticationProvider | None], TestClient]


@pytest.fixture
def make_client(session_factory: sessionmaker[Session]) -> ClientFactory:
    """Test-only app with a protected route using the real auth dependencies.

    Only the configured provider (a real verifier with local keys) and the
    database session are injected; no authentication step is bypassed.
    """

    def _make(provider: AuthenticationProvider | None) -> TestClient:
        app = FastAPI()

        @app.get("/companies/{company_id}/protected")
        def protected(context: CompanyContext) -> dict[str, str]:
            return {
                "user_id": str(context.user_id),
                "company_id": str(context.company_id),
                "membership_id": str(context.membership_id),
                "identity_id": str(context.identity_id),
            }

        def _db() -> Generator[Session, None, None]:
            with session_factory() as db:
                yield db

        app.dependency_overrides[get_authentication_provider] = lambda: provider
        app.dependency_overrides[get_db] = _db
        return TestClient(app)

    return _make


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
