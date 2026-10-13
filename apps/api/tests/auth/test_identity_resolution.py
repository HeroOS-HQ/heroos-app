"""Provider-independent identity resolution in the application layer (ADR-008).

In-memory SQLite: these prove what the *code* decides. The same lifecycle is
enforced again by Row-Level Security for the API role (tests/tenant_isolation).
"""

import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.auth.providers.development import (
    DEVELOPMENT_ISSUER,
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.db.models import Membership, User, UserIdentity
from tests.auth.conftest import (
    TEST_COGNITO_ISSUER,
    TEST_DEV_SECRET,
    ClientFactory,
    CognitoTokenFactory,
    SeedData,
    bearer,
)


@pytest.fixture
def client_for_cognito(
    make_client: ClientFactory, cognito_provider: CognitoAccessTokenProvider, seed: SeedData
) -> TestClient:
    return make_client(cognito_provider)


def url(company_id: uuid.UUID) -> str:
    return f"/companies/{company_id}/protected"


def dev_token(subject: str, **extra: object) -> str:
    if not extra:
        return issue_development_token(
            environment="development", secret=TEST_DEV_SECRET, subject=subject
        )
    now = int(time.time())
    claims = {"iss": DEVELOPMENT_ISSUER, "sub": subject, "iat": now, "exp": now + 300, **extra}
    return jwt.encode(claims, TEST_DEV_SECRET.get_secret_value(), algorithm="HS256")


def dev_client(make_client: ClientFactory) -> TestClient:
    return make_client(
        DevelopmentAuthenticationProvider(environment="development", secret=TEST_DEV_SECRET)
    )


def test_the_same_subject_under_another_issuer_is_a_different_identity(
    make_client: ClientFactory, seed: SeedData
) -> None:
    # carol-subject is bound under the Cognito issuer only. A development token
    # proving the same subject string is a different identity: denied.
    client = dev_client(make_client)
    assert (
        client.get(url(seed.company_a), headers=bearer(dev_token("carol-subject"))).status_code
        == 403
    )
    # alice is bound under both issuers: both reach the same User.
    assert client.get(url(seed.company_a), headers=bearer(dev_token("alice-subject"))).json()[
        "user_id"
    ] == str(seed.alice)


def test_email_claims_never_link_or_authorize(
    make_client: ClientFactory, seed: SeedData, session_factory: sessionmaker[Session]
) -> None:
    client = dev_client(make_client)
    token = dev_token(
        "unbound-subject", email="alice@example.test", email_verified=True, username="alice-subject"
    )

    assert client.get(url(seed.company_a), headers=bearer(token)).status_code == 403
    with session_factory() as db:
        assert db.query(User).count() == 3  # nothing was provisioned


def test_revoked_binding_is_denied_like_an_unknown_identity(
    client_for_cognito: TestClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
    make_cognito_token: CognitoTokenFactory,
) -> None:
    with session_factory() as db:
        db.execute(
            update(UserIdentity)
            .where(UserIdentity.id == seed.alice_identity)
            .values(status="revoked", revoked_at=UserIdentity.created_at)
        )
        db.commit()

    revoked = client_for_cognito.get(
        url(seed.company_a), headers=bearer(make_cognito_token("alice-subject"))
    )
    unknown = client_for_cognito.get(
        url(seed.company_a), headers=bearer(make_cognito_token("nobody"))
    )
    assert revoked.status_code == unknown.status_code == 403
    assert revoked.json() == unknown.json()


def test_suspended_user_is_denied_in_every_company_and_for_every_issuer(
    client_for_cognito: TestClient,
    make_client: ClientFactory,
    seed: SeedData,
    session_factory: sessionmaker[Session],
    make_cognito_token: CognitoTokenFactory,
) -> None:
    with session_factory() as db:
        db.execute(
            update(User)
            .where(User.id == seed.alice)
            .values(status="suspended", suspended_at=User.created_at)
        )
        db.commit()

    assert (
        client_for_cognito.get(
            url(seed.company_a), headers=bearer(make_cognito_token("alice-subject"))
        ).status_code
        == 403
    )
    assert (
        dev_client(make_client)
        .get(url(seed.company_a), headers=bearer(dev_token("alice-subject")))
        .status_code
        == 403
    )


def test_revoked_membership_is_denied(
    client_for_cognito: TestClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
    make_cognito_token: CognitoTokenFactory,
) -> None:
    with session_factory() as db:
        db.execute(
            update(Membership)
            .where(Membership.id == seed.alice_membership_a)
            .values(status="revoked", revoked_at=Membership.created_at)
        )
        db.commit()

    response = client_for_cognito.get(
        url(seed.company_a), headers=bearer(make_cognito_token("alice-subject"))
    )
    assert response.status_code == 403


def test_context_carries_internal_ids_never_the_external_subject(
    client_for_cognito: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    body = client_for_cognito.get(
        url(seed.company_a), headers=bearer(make_cognito_token("alice-subject"))
    ).json()
    assert body["identity_id"] == str(seed.alice_identity)
    assert "alice-subject" not in str(body)
    assert TEST_COGNITO_ISSUER not in str(body)
