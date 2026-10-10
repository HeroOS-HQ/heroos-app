"""The shipped Company endpoints through the real application and auth chain.

``create_app`` with staging settings (Cognito required, deployed headers), Cognito
access tokens signed with local keys and verified by the production provider and
``PyJWKClient`` code, and in-memory SQLite built from the real models. SQLite has
no RLS: the database layer is proven on PostgreSQL by
tests/tenant_isolation/test_api_routes.py.
"""

import time
import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.core.config import Settings
from app.db.models import Case
from app.db.session import get_db
from app.main import create_app
from tests.auth.conftest import (
    TEST_APP_CLIENT_ID,
    TEST_COGNITO_ISSUER,
    CognitoTokenFactory,
    SeedData,
    bearer,
)

UNAUTHENTICATED = {"detail": "Not authenticated"}
FORBIDDEN = {"detail": "Forbidden"}
NOT_FOUND = {"detail": "Not found"}


def staging_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        heroos_env="staging",
        database_url="postgresql+psycopg://heroos_app@db.test.invalid/heroos",
        heroos_auth_provider="cognito",
        heroos_cognito_issuer=TEST_COGNITO_ISSUER,
        heroos_cognito_app_client_id=TEST_APP_CLIENT_ID,
    )


@pytest.fixture
def cases_by_company(
    session_factory: sessionmaker[Session], seed: SeedData
) -> dict[uuid.UUID, uuid.UUID]:
    # SQLite cannot compile PostgreSQL's column-scoped ON DELETE SET NULL
    # (subject_id) on the cases FK, so the table is declared without it. The ORM
    # model is unchanged; tenant-safe FKs and RLS are proven on PostgreSQL.
    with session_factory() as db:
        db.execute(
            text(
                "CREATE TABLE cases (id CHAR(32) PRIMARY KEY, company_id CHAR(32) NOT NULL, "
                "subject_id CHAR(32), case_type VARCHAR(50) NOT NULL, title VARCHAR(200) NOT NULL, "
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )
        db.commit()
    created: dict[uuid.UUID, uuid.UUID] = {}
    with session_factory() as db:
        for company, label in ((seed.company_a, "A"), (seed.company_b, "B")):
            case = Case(company_id=company, case_type="general", title=f"Case {label}")
            db.add(case)
            db.flush()
            created[company] = case.id
        db.commit()
    return created


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    cognito_provider: CognitoAccessTokenProvider,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
) -> TestClient:
    app = create_app(staging_settings())

    def _db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: cognito_provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def paths(company: uuid.UUID | str, case: uuid.UUID | str) -> list[str]:
    return [
        f"/companies/{company}",
        f"/companies/{company}/cases",
        f"/companies/{company}/cases/{case}",
    ]


def test_member_reads_own_company_and_cases(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
) -> None:
    headers = bearer(make_cognito_token("alice-subject"))
    a, own_case = seed.company_a, cases_by_company[seed.company_a]

    company = client.get(f"/companies/{a}", headers=headers)
    assert company.status_code == 200
    assert company.json() == {"id": str(a), "name": "Company A"}

    listed = client.get(f"/companies/{a}/cases", headers=headers)
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [str(own_case)]
    assert set(listed.json()[0]) == {
        "id",
        "company_id",
        "subject_id",
        "case_type",
        "title",
        "created_at",
        "updated_at",
    }

    detail = client.get(f"/companies/{a}/cases/{own_case}", headers=headers)
    assert (detail.status_code, detail.json()["company_id"]) == (200, str(a))


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer", "Bearer not-a-jwt", "Basic YWxpY2U6c2VjcmV0"],
)
def test_missing_or_malformed_credentials_get_401(
    client: TestClient,
    seed: SeedData,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}
    for path in paths(seed.company_a, cases_by_company[seed.company_a]):
        response = client.get(path, headers=headers)
        assert (response.status_code, response.json()) == (401, UNAUTHENTICATED)
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"token_use": "id"}, id="id-token"),
        pytest.param({"client_id": "another-app-client"}, id="other-app-client"),
        pytest.param({"iss": "https://cognito-idp.test.invalid/other-pool"}, id="other-pool"),
        pytest.param({"exp": int(time.time()) - 1, "iat": int(time.time()) - 600}, id="expired"),
    ],
)
def test_invalid_cognito_tokens_get_401(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    overrides: dict[str, Any],
) -> None:
    token = make_cognito_token("alice-subject", **overrides)
    response = client.get(f"/companies/{seed.company_a}/cases", headers=bearer(token))
    assert (response.status_code, response.json()) == (401, UNAUTHENTICATED)


def test_token_signed_by_another_key_gets_401(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory, untrusted_key: Any
) -> None:
    token = make_cognito_token("alice-subject", key=untrusted_key)
    response = client.get(f"/companies/{seed.company_a}/cases", headers=bearer(token))
    assert response.status_code == 401


def test_other_company_is_forbidden_exactly_like_a_missing_company(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
) -> None:
    headers = bearer(make_cognito_token("alice-subject"))
    responses = [
        client.get(path, headers=headers)
        for path in [
            *paths(seed.company_b, cases_by_company[seed.company_b]),
            *paths(uuid.uuid4(), uuid.uuid4()),
            *paths("00000000-0000-0000-0000-000000000000", uuid.uuid4()),
        ]
    ]
    assert {(r.status_code, r.text) for r in responses} == {(403, '{"detail":"Forbidden"}')}


@pytest.mark.parametrize("subject", ["carol-subject", "unknown-subject"])
def test_user_without_membership_or_user_row_is_forbidden(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory, subject: str
) -> None:
    response = client.get(
        f"/companies/{seed.company_a}/cases", headers=bearer(make_cognito_token(subject))
    )
    assert (response.status_code, response.json()) == (403, FORBIDDEN)


def test_other_company_case_id_looks_missing(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
) -> None:
    headers = bearer(make_cognito_token("alice-subject"))
    a = seed.company_a
    guessed = client.get(
        f"/companies/{a}/cases/{cases_by_company[seed.company_b]}", headers=headers
    )
    random = client.get(f"/companies/{a}/cases/{uuid.uuid4()}", headers=headers)

    assert (
        (guessed.status_code, guessed.json())
        == (random.status_code, random.json())
        == (404, NOT_FOUND)
    )


@pytest.mark.parametrize("bad", ["not-a-uuid", "' OR 1=1 --"])
def test_malformed_ids_get_422_without_echo(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory, bad: str
) -> None:
    headers = bearer(make_cognito_token("alice-subject"))
    for path in (f"/companies/{bad}/cases", f"/companies/{seed.company_a}/cases/{bad}"):
        response = client.get(path, headers=headers)
        assert response.status_code == 422
        assert bad not in response.text


def test_write_methods_are_not_exposed(
    client: TestClient,
    seed: SeedData,
    make_cognito_token: CognitoTokenFactory,
    cases_by_company: dict[uuid.UUID, uuid.UUID],
) -> None:
    headers = bearer(make_cognito_token("alice-subject"))
    target = f"/companies/{seed.company_a}/cases/{cases_by_company[seed.company_a]}"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, target, headers=headers).status_code == 405


def test_authenticated_responses_are_not_cacheable_and_carry_no_token(
    client: TestClient, seed: SeedData, make_cognito_token: CognitoTokenFactory
) -> None:
    token = make_cognito_token("alice-subject")
    for status_path in (f"/companies/{seed.company_a}/cases", f"/companies/{seed.company_b}/cases"):
        response = client.get(status_path, headers=bearer(token))
        assert response.headers["cache-control"] == "no-store"
        assert token not in response.text
        assert token.split(".")[2] not in response.text
