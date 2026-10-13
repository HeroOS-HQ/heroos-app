"""Company roles and the Blueprint contract through the real application (M1-10C).

``create_app`` with staging settings, Cognito access tokens verified by the
production provider, and in-memory SQLite built from the real models (no RLS;
the database layer, column grants included, is proven on PostgreSQL in
tests/tenant_isolation/test_company_roles.py and test_company_blueprint.py).
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.models import AuthenticatedCompanyContext
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.db.base import Base
from app.db.models import CompanyBlueprint, Membership
from app.db.session import get_db
from app.main import create_app
from app.tenancy.dependencies import get_company_admin_scope
from tests.auth.conftest import CognitoTokenFactory, SeedData, bearer
from tests.auth.test_company_api import staging_settings

FORBIDDEN = (403, {"detail": "Forbidden"})
UNAUTHENTICATED = (401, {"detail": "Not authenticated"})


@pytest.fixture
def blueprints(session_factory: sessionmaker[Session], seed: SeedData) -> sessionmaker[Session]:
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(engine, tables=[CompanyBlueprint.__table__])
    return session_factory


def make_admin(sessions: sessionmaker[Session], company: uuid.UUID, user: uuid.UUID) -> None:
    with sessions() as db:
        db.execute(
            update(Membership)
            .where(Membership.company_id == company, Membership.user_id == user)
            .values(role="company_admin")
        )
        db.commit()


def stored_blueprint(
    sessions: sessionmaker[Session], company: uuid.UUID
) -> CompanyBlueprint | None:
    with sessions() as db:
        return db.scalar(select(CompanyBlueprint).where(CompanyBlueprint.company_id == company))


@pytest.fixture
def client(
    blueprints: sessionmaker[Session], cognito_provider: CognitoAccessTokenProvider
) -> TestClient:
    app = create_app(staging_settings())

    def _db() -> Generator[Session, None, None]:
        with blueprints() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: cognito_provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def alice(make_cognito_token: CognitoTokenFactory) -> dict[str, str]:
    return bearer(make_cognito_token("alice-subject"))


def test_membership_reports_the_server_side_role(
    client: TestClient, blueprints: sessionmaker[Session], seed: SeedData, alice: dict[str, str]
) -> None:
    url = f"/companies/{seed.company_a}/membership"
    member = client.get(url, headers=alice)
    assert member.status_code == 200
    assert member.json() == {
        "company_id": str(seed.company_a),
        "membership_id": str(seed.alice_membership_a),
        "role": "member",
        "can_update_blueprint": False,
    }

    make_admin(blueprints, seed.company_a, seed.alice)
    admin = client.get(url, headers=alice)
    assert (admin.json()["role"], admin.json()["can_update_blueprint"]) == ("company_admin", True)


def test_existing_members_are_not_administrators(
    client: TestClient, seed: SeedData, alice: dict[str, str]
) -> None:
    # The default role is member: nobody becomes an administrator implicitly.
    response = client.patch(
        f"/companies/{seed.company_a}/blueprint", headers=alice, json={"legal_name": "A LLC"}
    )
    assert (response.status_code, response.json()) == FORBIDDEN


def test_a_missing_blueprint_reads_as_empty_and_unconfirmed(
    client: TestClient, seed: SeedData, alice: dict[str, str]
) -> None:
    response = client.get(f"/companies/{seed.company_a}/blueprint", headers=alice)

    assert response.status_code == 200
    assert response.json() == {
        "company_id": str(seed.company_a),
        "legal_name": None,
        "industry": None,
        "employee_count": None,
        "licensing": {"location": None, "authority": None},
        "jurisdiction": {
            "readiness": "unconfirmed",
            "reason": "licensing_not_provided",
            "employment_jurisdiction": None,
            "confirmed_at": None,
            "guidance_allowed": False,
        },
        "updated_at": None,
    }


def test_admin_updates_only_the_fields_sent(
    client: TestClient, blueprints: sessionmaker[Session], seed: SeedData, alice: dict[str, str]
) -> None:
    make_admin(blueprints, seed.company_a, seed.alice)
    url = f"/companies/{seed.company_a}/blueprint"

    first = client.patch(
        url,
        headers=alice,
        json={
            "legal_name": "Alpha Trading LLC",
            "employee_count": 12,
            "licensing": {"location": "other", "authority": "Jebel Ali Free Zone Authority"},
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["licensing"] == {"location": "other", "authority": "Jebel Ali Free Zone Authority"}
    # "Other" never means UAE Federal / MOHRE: unresolved until confirmed.
    assert body["jurisdiction"]["readiness"] == "unconfirmed"
    assert body["jurisdiction"]["reason"] == "awaiting_confirmation"
    assert body["jurisdiction"]["employment_jurisdiction"] is None
    assert body["jurisdiction"]["guidance_allowed"] is False

    second = client.patch(url, headers=alice, json={"industry": "Logistics"})
    assert second.status_code == 200
    assert (second.json()["legal_name"], second.json()["industry"]) == (
        "Alpha Trading LLC",
        "Logistics",
    )
    assert second.json()["licensing"]["location"] == "other"

    cleared = client.patch(url, headers=alice, json={"licensing": None, "employee_count": None})
    assert cleared.json()["licensing"] == {"location": None, "authority": None}
    assert cleared.json()["employee_count"] is None
    stored = stored_blueprint(blueprints, seed.company_a)
    assert stored is not None
    assert (stored.legal_name, stored.industry, stored.licensing_location) == (
        "Alpha Trading LLC",
        "Logistics",
        None,
    )
    assert client.get(url, headers=alice).json() == cleared.json()


@pytest.mark.parametrize(
    ("location", "reason"),
    [("difc", "awaiting_confirmation"), ("not_sure", "licensing_not_sure")],
)
def test_licensing_answers_never_confirm_a_jurisdiction(
    client: TestClient,
    blueprints: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
    location: str,
    reason: str,
) -> None:
    make_admin(blueprints, seed.company_a, seed.alice)
    response = client.patch(
        f"/companies/{seed.company_a}/blueprint",
        headers=alice,
        json={"licensing": {"location": location}},
    )
    jurisdiction = response.json()["jurisdiction"]
    assert (jurisdiction["readiness"], jurisdiction["reason"]) == ("unconfirmed", reason)
    assert jurisdiction["employment_jurisdiction"] is None
    assert jurisdiction["guidance_allowed"] is False


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"role": "company_admin"}, id="role"),
        pytest.param({"company_id": str(uuid.uuid4())}, id="company-id"),
        pytest.param({"id": str(uuid.uuid4())}, id="id"),
        pytest.param({"employment_jurisdiction": "difc"}, id="employment-jurisdiction"),
        pytest.param({"jurisdiction": {"readiness": "supported_confirmed"}}, id="readiness"),
        pytest.param({"confirmed_licensing_location": "difc"}, id="confirmation-basis"),
        pytest.param({"jurisdiction_confirmed_at": "2026-10-13T00:00:00Z"}, id="confirmed-at"),
        pytest.param({"primary_jurisdiction": "DIFC"}, id="legacy-label"),
        pytest.param(
            {"licensing": {"location": "difc", "confirmed": True}}, id="nested-unknown-field"
        ),
    ],
)
def test_mass_assignment_is_refused(
    client: TestClient,
    blueprints: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
    body: dict[str, Any],
) -> None:
    make_admin(blueprints, seed.company_a, seed.alice)
    response = client.patch(f"/companies/{seed.company_a}/blueprint", headers=alice, json=body)

    assert response.status_code == 422
    assert {error["type"] for error in response.json()["detail"]} == {"extra_forbidden"}
    assert stored_blueprint(blueprints, seed.company_a) is None
    with blueprints() as db:
        assert db.scalar(select(Membership.role).where(Membership.user_id == seed.alice)) == (
            "company_admin"
        )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"licensing": {"location": "difc", "authority": "DIFC"}}, id="authority-difc"),
        pytest.param(
            {"licensing": {"location": "not_sure", "authority": "x"}}, id="authority-unsure"
        ),
        pytest.param({"licensing": {"location": "adgm"}}, id="unknown-location"),
        pytest.param({"licensing": {"location": "DIFC"}}, id="wrong-case"),
        pytest.param({"licensing": {"authority": "x"}}, id="location-missing"),
        pytest.param({"licensing": {"location": "other", "authority": " JAFZA"}}, id="padded"),
        pytest.param({"licensing": {"location": "other", "authority": ""}}, id="empty"),
        pytest.param({"licensing": {"location": "other", "authority": "a\nb"}}, id="control"),
        pytest.param({"licensing": {"location": "other", "authority": "x" * 121}}, id="too-long"),
        pytest.param({"licensing": "difc"}, id="not-an-object"),
        pytest.param({"legal_name": ""}, id="empty-name"),
        pytest.param({"legal_name": "x" * 201}, id="long-name"),
        pytest.param({"employee_count": -1}, id="negative-count"),
        pytest.param({"employee_count": "12"}, id="string-count"),
        pytest.param({"employee_count": True}, id="boolean-count"),
        pytest.param({"employee_count": 1.5}, id="float-count"),
    ],
)
def test_invalid_blueprint_input_is_refused_without_echo(
    client: TestClient,
    blueprints: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
    body: dict[str, Any],
) -> None:
    make_admin(blueprints, seed.company_a, seed.alice)
    response = client.patch(f"/companies/{seed.company_a}/blueprint", headers=alice, json=body)

    assert response.status_code == 422
    for error in response.json()["detail"]:
        assert set(error) <= {"type", "loc", "msg"}
    assert "JAFZA" not in response.text
    assert stored_blueprint(blueprints, seed.company_a) is None


def test_admin_of_one_company_cannot_touch_another(
    client: TestClient,
    blueprints: sessionmaker[Session],
    seed: SeedData,
    alice: dict[str, str],
) -> None:
    make_admin(blueprints, seed.company_a, seed.alice)
    for company in (seed.company_b, uuid.uuid4()):
        base = f"/companies/{company}"
        for response in (
            client.get(f"{base}/blueprint", headers=alice),
            client.get(f"{base}/membership", headers=alice),
            client.patch(f"{base}/blueprint", headers=alice, json={"legal_name": "Taken"}),
        ):
            assert (response.status_code, response.json()) == FORBIDDEN
    assert stored_blueprint(blueprints, seed.company_b) is None


def test_unauthenticated_requests_get_401(client: TestClient, seed: SeedData) -> None:
    for response in (
        client.get(f"/companies/{seed.company_a}/membership"),
        client.get(f"/companies/{seed.company_a}/blueprint"),
        client.patch(f"/companies/{seed.company_a}/blueprint", json={"legal_name": "x"}),
    ):
        assert (response.status_code, response.json()) == UNAUTHENTICATED


def test_role_is_rechecked_inside_the_write_transaction(
    blueprints: sessionmaker[Session], seed: SeedData
) -> None:
    # A context that still says company_admin (read at authorization) while the
    # Membership is member now: the write scope refuses with the generic 403.
    stale = AuthenticatedCompanyContext(
        user_id=seed.alice,
        company_id=seed.company_a,
        membership_id=seed.alice_membership_a,
        identity_id=seed.alice_identity,
        role="company_admin",
    )
    with blueprints() as db, pytest.raises(HTTPException) as exc_info:
        get_company_admin_scope(stale, db)
    assert (exc_info.value.status_code, exc_info.value.detail) == (403, "Forbidden")

    make_admin(blueprints, seed.company_a, seed.alice)
    with blueprints() as db:
        assert get_company_admin_scope(stale, db).company_id == seed.company_a
