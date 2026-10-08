"""Guessed and manipulated IDs through the real HTTP dependency chain.

Bearer token -> provider -> User -> Membership (candidate-scope bootstrap) ->
AuthenticatedCompanyContext -> CompanyDb (tenant context) -> repositories -> RLS,
served by the runtime role on a single pooled connection. The routes exist only
in this test application; HeroOS ships no such endpoints yet.

Response semantics:

- ``/companies/{other_company}/...`` -> 403, identical to a non-existent Company
  (M1-05: Membership decides).
- ``/companies/{own_company}/cases/{other_company_case}`` -> 404, identical to a
  case ID that does not exist anywhere.
"""

import uuid
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.providers.development import (
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.db.models import Case
from app.db.session import get_db
from app.repositories import ResourceNotFoundError, case_subjects, cases, companies
from app.tenancy.dependencies import CompanyDb
from tests.tenant_isolation.conftest import TenantDatabase, Tenants, tenant_setting

SECRET = SecretStr("tenant-isolation-test-secret-0123456789abcdef")
NOT_FOUND = {"detail": "Not found"}
FORBIDDEN = {"detail": "Forbidden"}


class CaseIn(BaseModel):
    case_type: str
    title: str
    subject_id: uuid.UUID | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _case_out(case: Case) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "company_id": str(case.company_id),
        "subject_id": None if case.subject_id is None else str(case.subject_id),
        "title": case.title,
    }


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/companies/{company_id}")
    def get_company(scope: CompanyDb) -> dict[str, str]:
        company = companies.get_company(scope)
        if company is None:
            raise _not_found()
        return {"id": str(company.id), "name": company.name}

    @app.get("/companies/{company_id}/cases")
    def list_cases(scope: CompanyDb) -> list[dict[str, Any]]:
        return [_case_out(case) for case in cases.list_cases(scope)]

    @app.post("/companies/{company_id}/cases", status_code=201)
    def create_case(body: CaseIn, scope: CompanyDb) -> dict[str, Any]:
        try:
            case = cases.create_case(
                scope, case_type=body.case_type, title=body.title, subject_id=body.subject_id
            )
        except ResourceNotFoundError:
            raise _not_found() from None
        scope.commit()
        return _case_out(case)

    @app.get("/companies/{company_id}/cases/{case_id}")
    def get_case(case_id: uuid.UUID, scope: CompanyDb) -> dict[str, Any]:
        case = cases.get_case(scope, case_id)
        if case is None:
            raise _not_found()
        return _case_out(case)

    @app.patch("/companies/{company_id}/cases/{case_id}")
    def update_case(case_id: uuid.UUID, body: CaseIn, scope: CompanyDb) -> dict[str, Any]:
        case = cases.update_case(scope, case_id, case_type=body.case_type, title=body.title)
        if case is None:
            raise _not_found()
        scope.commit()
        return _case_out(case)

    @app.delete("/companies/{company_id}/cases/{case_id}", status_code=204)
    def delete_case(case_id: uuid.UUID, scope: CompanyDb) -> Response:
        if not cases.delete_case(scope, case_id):
            raise _not_found()
        scope.commit()
        return Response(status_code=204)

    @app.get("/companies/{company_id}/case-subjects/{subject_id}")
    def get_subject(subject_id: uuid.UUID, scope: CompanyDb) -> dict[str, str]:
        subject = case_subjects.get_case_subject(scope, subject_id)
        if subject is None:
            raise _not_found()
        return {"id": str(subject.id), "display_name": subject.display_name}

    return app


@pytest.fixture
def http_sessions(tenant_database: TenantDatabase) -> Iterator[sessionmaker[Session]]:
    # One pooled runtime connection shared by every request in a test.
    engine = create_engine(
        tenant_database.runtime_url, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


@pytest.fixture
def client(http_sessions: sessionmaker[Session], tenants: Tenants) -> TestClient:
    app = build_app()

    def _db() -> Generator[Session, None, None]:
        with http_sessions() as db:
            yield db

    provider = DevelopmentAuthenticationProvider(environment="development", secret=SECRET)
    app.dependency_overrides[get_authentication_provider] = lambda: provider
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def auth(subject: str) -> dict[str, str]:
    token = issue_development_token(environment="development", secret=SECRET, subject=subject)
    return {"Authorization": f"Bearer {token}"}


ALICE = "alice-subject"
BOB = "bob-subject"


def test_members_read_their_own_company(client: TestClient, tenants: Tenants) -> None:
    for subject, tenant in ((ALICE, tenants.a), (BOB, tenants.b)):
        base = f"/companies/{tenant.company}"
        assert client.get(base, headers=auth(subject)).json()["id"] == str(tenant.company)
        case = client.get(f"{base}/cases/{tenant.case}", headers=auth(subject))
        assert case.status_code == 200
        assert case.json()["company_id"] == str(tenant.company)
        listed = client.get(f"{base}/cases", headers=auth(subject)).json()
        assert [c["id"] for c in listed] == [str(tenant.case)]
        subject_response = client.get(
            f"{base}/case-subjects/{tenant.subject}", headers=auth(subject)
        )
        assert subject_response.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/companies/{own}/cases/{other_case}",
        "/companies/{own}/case-subjects/{other_subject}",
        "/companies/{own}/cases/{other_subject}",
    ],
)
def test_guessed_other_company_ids_look_missing(
    client: TestClient, tenants: Tenants, path: str
) -> None:
    for subject, own, other in ((ALICE, tenants.a, tenants.b), (BOB, tenants.b, tenants.a)):
        guessed = client.get(
            path.format(own=own.company, other_case=other.case, other_subject=other.subject),
            headers=auth(subject),
        )
        random = client.get(
            path.format(own=own.company, other_case=uuid.uuid4(), other_subject=uuid.uuid4()),
            headers=auth(subject),
        )

        assert guessed.status_code == random.status_code == 404
        assert guessed.json() == random.json() == NOT_FOUND


def test_other_company_path_is_forbidden_like_a_missing_company(
    client: TestClient, tenants: Tenants
) -> None:
    b = tenants.b
    for path in (
        f"/companies/{b.company}",
        f"/companies/{b.company}/cases",
        f"/companies/{b.company}/cases/{b.case}",
        f"/companies/{b.company}/case-subjects/{b.subject}",
    ):
        response = client.get(path, headers=auth(ALICE))
        assert response.status_code == 403
        assert response.json() == FORBIDDEN

    missing = client.get(f"/companies/{uuid.uuid4()}/cases", headers=auth(ALICE))
    assert (missing.status_code, missing.json()) == (403, FORBIDDEN)


def test_cross_company_update_and_delete_look_missing_and_change_nothing(
    client: TestClient, tenants: Tenants
) -> None:
    a, b = tenants.a, tenants.b
    target = f"/companies/{a.company}/cases/{b.case}"
    body = {"case_type": "probation", "title": "tampered"}

    assert client.patch(target, json=body, headers=auth(ALICE)).status_code == 404
    assert client.delete(target, headers=auth(ALICE)).status_code == 404
    assert (
        client.patch(f"/companies/{b.company}/cases/{b.case}", json=body, headers=auth(ALICE))
    ).status_code == 403
    assert (
        client.delete(f"/companies/{b.company}/cases/{b.case}", headers=auth(ALICE)).status_code
        == 403
    )

    still = client.get(f"/companies/{b.company}/cases/{b.case}", headers=auth(BOB))
    assert still.status_code == 200
    assert still.json()["title"] == "Case B"


def test_create_ignores_client_company_id_and_rejects_foreign_subject(
    client: TestClient, tenants: Tenants
) -> None:
    a, b = tenants.a, tenants.b
    created = client.post(
        f"/companies/{a.company}/cases",
        json={"case_type": "probation", "title": "Mine", "company_id": str(b.company)},
        headers=auth(ALICE),
    )
    assert created.status_code == 201
    assert created.json()["company_id"] == str(a.company)

    foreign_subject = client.post(
        f"/companies/{a.company}/cases",
        json={"case_type": "probation", "title": "x", "subject_id": str(b.subject)},
        headers=auth(ALICE),
    )
    assert (foreign_subject.status_code, foreign_subject.json()) == (404, NOT_FOUND)

    bob_view = client.get(f"/companies/{b.company}/cases", headers=auth(BOB)).json()
    assert [c["id"] for c in bob_view] == [str(b.case)]


def test_same_company_writes_succeed(client: TestClient, tenants: Tenants) -> None:
    a = tenants.a
    base = f"/companies/{a.company}/cases"
    updated = client.patch(
        f"{base}/{a.case}", json={"case_type": "probation", "title": "Renamed"}, headers=auth(ALICE)
    )
    assert (updated.status_code, updated.json()["title"]) == (200, "Renamed")

    created = client.post(
        base,
        json={"case_type": "recruitment", "title": "Hire", "subject_id": str(a.subject)},
        headers=auth(ALICE),
    )
    assert created.status_code == 201
    assert client.delete(f"{base}/{created.json()['id']}", headers=auth(ALICE)).status_code == 204
    assert client.get(f"{base}/{created.json()['id']}", headers=auth(ALICE)).status_code == 404


def test_requests_leave_no_tenant_context_on_the_pooled_connection(
    client: TestClient, http_sessions: sessionmaker[Session], tenants: Tenants
) -> None:
    for subject, tenant in ((ALICE, tenants.a), (BOB, tenants.b), (ALICE, tenants.a)):
        listed = client.get(f"/companies/{tenant.company}/cases", headers=auth(subject)).json()
        assert {c["company_id"] for c in listed} == {str(tenant.company)}
        with http_sessions() as db:
            assert tenant_setting(db) in (None, "")


# --- M1-05 regression against PostgreSQL with RLS ----------------------------


def test_m1_05_semantics_preserved_under_rls(client: TestClient, tenants: Tenants) -> None:
    a, b = tenants.a, tenants.b
    url = f"/companies/{a.company}/cases"

    missing = client.get(url)
    assert (missing.status_code, missing.json()) == (401, {"detail": "Not authenticated"})

    invalid = client.get(url, headers={"Authorization": "Bearer not-a-jwt"})
    assert invalid.status_code == 401

    for subject in ("stranger", "carol-subject"):  # unknown User, no Membership
        denied = client.get(url, headers=auth(subject))
        assert (denied.status_code, denied.json()) == (403, FORBIDDEN)

    assert client.get(f"/companies/{b.company}/cases", headers=auth(ALICE)).status_code == 403
    assert client.get(f"/companies/{a.company}/cases", headers=auth(BOB)).status_code == 403
    assert client.get(url, headers=auth(ALICE)).status_code == 200


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        pytest.param("00000000-0000-0000-0000-000000000000", 403, id="nil-uuid"),
        pytest.param("not-a-uuid", 422, id="malformed"),
        pytest.param("' OR 1=1 --", 422, id="injection"),
    ],
)
def test_invalid_company_identifiers_fail_safely(
    client: TestClient, tenants: Tenants, company: str, expected: int
) -> None:
    response = client.get(f"/companies/{company}/cases", headers=auth(ALICE))

    assert response.status_code == expected
    assert str(tenants.a.case) not in response.text
    assert str(tenants.b.case) not in response.text
