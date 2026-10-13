"""Founder self-registration routes through the real application (M1-10C).

Request-level behaviour that needs no database function: the activation
switch, authentication, and strict validation (no client-chosen identity,
Company, role or administrator). Registration itself runs in PostgreSQL
(``heroos_register_company``) and is proven in
tests/tenant_isolation/test_founder_registration.py.
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import (
    TEST_APP_CLIENT_ID,
    TEST_COGNITO_ISSUER,
    CognitoTokenFactory,
    SeedData,
    bearer,
)

URL = "/company-registrations"


def settings(enabled: bool) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
        heroos_self_registration_enabled=enabled,
    )


def make_app_client(
    enabled: bool,
    session_factory: sessionmaker[Session],
    provider: CognitoAccessTokenProvider,
) -> TestClient:
    app = create_app(settings(enabled))

    def _db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    seed: SeedData,
) -> TestClient:
    return make_app_client(True, session_factory, cognito_provider)


def test_self_registration_is_off_unless_enabled(
    session_factory: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    make_cognito_token: CognitoTokenFactory,
    seed: SeedData,
) -> None:
    assert Settings.model_fields["heroos_self_registration_enabled"].default is False
    disabled = make_app_client(False, session_factory, cognito_provider)
    for headers in ({}, bearer(make_cognito_token("new-founder-subject"))):
        response = disabled.post(URL, headers=headers, json={"company_name": "Acme"})
        assert (response.status_code, response.json()) == (404, {"detail": "Not found"})


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-jwt", "Basic YWxpY2U6c2VjcmV0"])
def test_registration_needs_a_verified_credential(
    client: TestClient, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    response = client.post(URL, headers=headers, json={"company_name": "Acme"})
    assert (response.status_code, response.json()) == (401, {"detail": "Not authenticated"})


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"token_use": "id"}, id="id-token"),
        pytest.param({"client_id": "another-app-client"}, id="other-client"),
        pytest.param({"iss": "https://cognito-idp.test.invalid/other-pool"}, id="other-issuer"),
    ],
)
def test_registration_refuses_tokens_the_provider_rejects(
    client: TestClient, make_cognito_token: CognitoTokenFactory, overrides: dict[str, Any]
) -> None:
    token = make_cognito_token("new-founder-subject", **overrides)
    response = client.post(URL, headers=bearer(token), json={"company_name": "Acme"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        # Identity, Company and authority are never chosen by the client.
        pytest.param({"company_name": "Acme", "company_id": str(uuid.uuid4())}, id="company-id"),
        pytest.param({"company_name": "Acme", "user_id": str(uuid.uuid4())}, id="user-id"),
        pytest.param({"company_name": "Acme", "issuer": "https://evil.test/"}, id="issuer"),
        pytest.param({"company_name": "Acme", "subject": "someone-else"}, id="subject"),
        pytest.param({"company_name": "Acme", "role": "company_admin"}, id="role"),
        pytest.param({"company_name": "Acme", "administrator": "x"}, id="administrator"),
        pytest.param({"company_name": "Acme", "email": "ceo@acme.test"}, id="email"),
        pytest.param(
            {"company_name": "Acme", "blueprint": {"employment_jurisdiction": "difc"}},
            id="confirmation",
        ),
        pytest.param(
            {"company_name": "Acme", "blueprint": {"company_id": str(uuid.uuid4())}},
            id="blueprint-company-id",
        ),
    ],
)
def test_client_supplied_identity_company_or_role_is_refused(
    client: TestClient, make_cognito_token: CognitoTokenFactory, body: dict[str, Any]
) -> None:
    response = client.post(
        URL, headers=bearer(make_cognito_token("new-founder-subject")), json=body
    )
    assert response.status_code == 422
    assert {error["type"] for error in response.json()["detail"]} == {"extra_forbidden"}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing-name"),
        pytest.param({"company_name": ""}, id="empty"),
        pytest.param({"company_name": " Acme"}, id="padded"),
        pytest.param({"company_name": "Acme\nLtd"}, id="control"),
        pytest.param({"company_name": "x" * 201}, id="too-long"),
        pytest.param({"company_name": 42}, id="not-text"),
        pytest.param(
            {"company_name": "Acme", "blueprint": {"licensing": {"location": "adgm"}}},
            id="unknown-licensing",
        ),
        pytest.param(
            {
                "company_name": "Acme",
                "blueprint": {"licensing": {"location": "difc", "authority": "X"}},
            },
            id="authority-with-difc",
        ),
    ],
)
def test_invalid_registration_input_is_refused_without_echo(
    client: TestClient, make_cognito_token: CognitoTokenFactory, body: dict[str, Any]
) -> None:
    response = client.post(
        URL, headers=bearer(make_cognito_token("new-founder-subject")), json=body
    )
    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) <= {"type", "loc", "msg"}
    assert "Acme\nLtd" not in response.text


def test_workspace_discovery_is_denied_to_unprovisioned_identities(
    client: TestClient, make_cognito_token: CognitoTokenFactory
) -> None:
    # Before registration HeroOS does not know the identity: the generic 403,
    # exactly like every Company route.
    response = client.get("/me/companies", headers=bearer(make_cognito_token("unknown-subject")))
    assert (response.status_code, response.json()) == (403, {"detail": "Forbidden"})
    assert client.get("/me/companies").status_code == 401
