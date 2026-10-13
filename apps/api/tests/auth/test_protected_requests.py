"""End-to-end protected requests through the real FastAPI auth dependency chain.

Bearer token -> provider -> VerifiedIdentity -> HeroOS User -> Membership ->
AuthenticatedCompanyContext. The route exists only in the test application.
"""

import logging
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.auth.providers.development import (
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from tests.auth.conftest import (
    TEST_APP_CLIENT_ID,
    TEST_DEV_SECRET,
    ClientFactory,
    CognitoTokenFactory,
    SeedData,
    bearer,
)

UNAUTHENTICATED = {"detail": "Not authenticated"}
FORBIDDEN = {"detail": "Forbidden"}


def url(company_id: uuid.UUID | str) -> str:
    return f"/companies/{company_id}/protected"


@pytest.fixture
def client(
    make_client: ClientFactory, cognito_provider: CognitoAccessTokenProvider, seed: SeedData
) -> TestClient:
    return make_client(cognito_provider)


# A. Missing credentials
def test_missing_credentials_rejected(client: TestClient, seed: SeedData) -> None:
    response = client.get(url(seed.company_a))

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED
    assert response.headers["WWW-Authenticate"] == "Bearer"


# B. Malformed bearer credentials
@pytest.mark.parametrize(
    "authorization",
    ["Bearer", "Bearer ", "Bearer not-a-jwt", "Bearer a.b.c", "Basic YWxpY2U6c2VjcmV0", "alice"],
)
def test_malformed_credentials_rejected(
    client: TestClient, seed: SeedData, authorization: str
) -> None:
    response = client.get(url(seed.company_a), headers={"Authorization": authorization})

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


# C-G. Invalid signature, expiry, issuer, App Client and token_use
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"exp": int(time.time()) - 60, "iat": int(time.time()) - 660}, id="expired"),
        pytest.param({"iss": "https://cognito-idp.test.invalid/other-pool"}, id="wrong-issuer"),
        pytest.param({"client_id": "another-app-client"}, id="wrong-app-client"),
        pytest.param({"token_use": "id"}, id="wrong-token-use"),
        pytest.param({"aud": TEST_APP_CLIENT_ID, "token_use": "id"}, id="id-token"),
    ],
)
def test_invalid_claims_rejected(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    overrides: dict[str, object],
) -> None:
    response = client.get(url(seed.company_a), headers=bearer(make_cognito_token(**overrides)))

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_invalid_signature_rejected(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    untrusted_key: object,
) -> None:
    token = make_cognito_token(key=untrusted_key)

    response = client.get(url(seed.company_a), headers=bearer(token))

    assert response.status_code == 401


def test_no_configured_provider_rejects_everything(
    make_client: ClientFactory, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    client = make_client(None)

    response = client.get(url(seed.company_a), headers=bearer(make_cognito_token()))

    assert response.status_code == 401


def test_resource_bound_access_token_with_aud_allowed(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    token = make_cognito_token("alice-subject", aud="https://api.test.invalid")

    assert client.get(url(seed.company_a), headers=bearer(token)).status_code == 200


# H. Verified identity without a HeroOS User
def test_verified_identity_without_user_forbidden(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    response = client.get(url(seed.company_a), headers=bearer(make_cognito_token("stranger")))

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


# I. HeroOS User with no Membership in the requested Company
def test_user_without_membership_forbidden(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    response = client.get(url(seed.company_a), headers=bearer(make_cognito_token("carol-subject")))

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_unknown_user_and_missing_membership_are_indistinguishable(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    unknown = client.get(url(seed.company_a), headers=bearer(make_cognito_token("stranger")))
    no_membership = client.get(
        url(seed.company_a), headers=bearer(make_cognito_token("carol-subject"))
    )
    missing_company = client.get(url(uuid.uuid4()), headers=bearer(make_cognito_token()))

    assert {r.status_code for r in (unknown, no_membership, missing_company)} == {403}
    assert unknown.json() == no_membership.json() == missing_company.json() == FORBIDDEN


# J. Member of the requested Company
def test_member_allowed_with_trusted_context(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    response = client.get(url(seed.company_a), headers=bearer(make_cognito_token("alice-subject")))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(seed.alice),
        "company_id": str(seed.company_a),
        "membership_id": str(seed.alice_membership_a),
        "identity_id": str(seed.alice_identity),
    }


# K. Member of Company A requesting Company B
def test_cross_company_access_forbidden(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    alice = bearer(make_cognito_token("alice-subject"))
    bob = bearer(make_cognito_token("bob-subject"))

    assert client.get(url(seed.company_b), headers=alice).status_code == 403
    assert client.get(url(seed.company_a), headers=bob).status_code == 403
    assert client.get(url(seed.company_b), headers=bob).status_code == 200


# L. Client-supplied Company identifiers never authorize
def test_changing_company_id_is_reauthorized_server_side(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    alice = bearer(make_cognito_token("alice-subject"))

    assert client.get(url(seed.company_a), headers=alice).status_code == 200
    assert client.get(url(seed.company_b), headers=alice).status_code == 403
    assert client.get(url(uuid.uuid4()), headers=alice).status_code == 403


def test_company_claims_headers_and_query_do_not_authorize(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    token = make_cognito_token(
        "alice-subject",
        company_id=str(seed.company_b),
        **{"custom:company_id": str(seed.company_b)},
    )
    headers = {**bearer(token), "X-Company-ID": str(seed.company_b), "X-User-ID": str(seed.bob)}

    response = client.get(
        url(seed.company_b), headers=headers, params={"company_id": str(seed.company_b)}
    )

    assert response.status_code == 403


def test_identity_headers_without_bearer_token_rejected(client: TestClient, seed: SeedData) -> None:
    response = client.get(
        url(seed.company_a),
        headers={"X-User-ID": str(seed.alice), "X-Dev-User": "alice-subject"},
    )

    assert response.status_code == 401


# M. Development token in development configuration
def test_development_token_authorizes_member(make_client: ClientFactory, seed: SeedData) -> None:
    client = make_client(
        DevelopmentAuthenticationProvider(environment="development", secret=TEST_DEV_SECRET)
    )
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject="alice-subject"
    )

    assert client.get(url(seed.company_a), headers=bearer(token)).status_code == 200
    assert client.get(url(seed.company_b), headers=bearer(token)).status_code == 403


def test_development_token_rejected_by_cognito_provider(client: TestClient, seed: SeedData) -> None:
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject="alice-subject"
    )

    assert client.get(url(seed.company_a), headers=bearer(token)).status_code == 401


def test_development_token_for_unknown_subject_grants_nothing(
    make_client: ClientFactory, seed: SeedData
) -> None:
    client = make_client(
        DevelopmentAuthenticationProvider(environment="development", secret=TEST_DEV_SECRET)
    )
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject="made-up-subject"
    )

    assert client.get(url(seed.company_a), headers=bearer(token)).status_code == 403


# P. Credentials never reach logs or responses
def test_bearer_tokens_not_logged_or_echoed(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    untrusted_key: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    tokens = {
        "valid": make_cognito_token("alice-subject"),
        "cross-company": make_cognito_token("alice-subject"),
        "unknown-user": make_cognito_token("stranger"),
        "bad-signature": make_cognito_token(key=untrusted_key),
        "expired": make_cognito_token(exp=int(time.time()) - 60, iat=int(time.time()) - 660),
        "garbage": "definitely-not-a-jwt-but-still-a-secret-credential",
    }
    targets = {"cross-company": seed.company_b}

    bodies = []
    for name, token in tokens.items():
        response = client.get(url(targets.get(name, seed.company_a)), headers=bearer(token))
        bodies.append(response.text + str(response.headers))

    assert any("Authentication rejected" in m for m in caplog.messages)
    assert any("Authorization denied" in m for m in caplog.messages)
    for token in tokens.values():
        assert token not in caplog.text
        assert all(token not in body for body in bodies)
        # No fragment of the token (e.g. its signature segment) either.
        assert token.split(".")[-1] not in caplog.text
    assert "Bearer" not in caplog.text.replace("WWW-Authenticate", "")
