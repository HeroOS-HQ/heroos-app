"""Private objects are reachable only inside the trusted Company namespace.

Service-level proofs call ``PrivateObjectService`` directly with real
``CompanyScope`` values. The HTTP proofs use a test-only router on the real
dependency chain (bearer token -> User -> Membership -> CompanyScope ->
PrivateObjectService); no such route exists in the application.
"""

import inspect
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Body, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import get_authentication_provider
from app.auth.models import AuthenticatedCompanyContext
from app.auth.providers.development import (
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.db.session import get_db
from app.storage import dependencies as storage_dependencies
from app.storage.dependencies import ObjectStorage, get_private_object_service
from app.storage.errors import ObjectNotFoundError, StorageConfigurationError, StorageError
from app.storage.local import LocalFilesystemStorage
from app.storage.service import PrivateObjectService
from app.tenancy.dependencies import CompanyDb
from app.tenancy.scope import CompanyScope
from tests.auth.conftest import (  # noqa: F401  (fixtures)
    TEST_DEV_SECRET,
    SeedData,
    development_provider,
    seed,
    session_factory,
)

COMPANY_A = uuid.UUID("0b6f2c1e-3a8d-4f57-9c2e-6d1a4b7e8f90")
COMPANY_B = uuid.UUID("7c1d3e5f-9a2b-4c6d-8e0f-1a3b5c7d9e2f")


def scope(company_id: uuid.UUID) -> CompanyScope:
    # Storage never touches the session; the scope carries the trusted Company.
    return CompanyScope(session=Session(), company_id=company_id)


@pytest.fixture
def service(storage: LocalFilesystemStorage) -> PrivateObjectService:
    return PrivateObjectService(storage)


# Service level ---------------------------------------------------------------


def test_each_company_reads_and_deletes_its_own_objects(service: PrivateObjectService) -> None:
    a, b = scope(COMPANY_A), scope(COMPANY_B)
    object_a = service.store(a, b"object A")
    object_b = service.store(b, b"object B")

    assert service.read(a, object_a) == b"object A"
    assert service.read(b, object_b) == b"object B"
    assert service.exists(a, object_a) and service.exists(b, object_b)
    assert service.delete(a, object_a) is True
    assert service.delete(b, object_b) is True
    assert not service.exists(a, object_a) and not service.exists(b, object_b)


@pytest.mark.parametrize(("attacker", "owner"), [(COMPANY_A, COMPANY_B), (COMPANY_B, COMPANY_A)])
def test_known_object_id_of_another_company_grants_nothing(
    service: PrivateObjectService, attacker: uuid.UUID, owner: uuid.UUID
) -> None:
    victim = service.store(scope(owner), b"other company's object")
    never_existed = uuid.uuid4()

    with pytest.raises(ObjectNotFoundError) as cross_tenant:
        service.read(scope(attacker), victim)
    with pytest.raises(ObjectNotFoundError) as missing:
        service.read(scope(attacker), never_existed)
    # Indistinguishable from an object that never existed.
    assert str(cross_tenant.value) == str(missing.value)
    assert service.exists(scope(attacker), victim) is False
    assert service.delete(scope(attacker), victim) is False

    # The owner's object is untouched.
    assert service.read(scope(owner), victim) == b"other company's object"


def test_store_cannot_target_an_existing_or_foreign_object(
    service: PrivateObjectService, storage_root: Path
) -> None:
    victim = service.store(scope(COMPANY_B), b"B original")

    created = {service.store(scope(COMPANY_A), b"A attempt") for _ in range(5)}

    # Object IDs are always server-generated: there is no overwrite path.
    assert victim not in created
    assert service.read(scope(COMPANY_B), victim) == b"B original"
    assert not storage_root.joinpath("companies", str(COMPANY_A), str(victim)).exists()


def test_service_accepts_no_caller_supplied_company_key_or_path() -> None:
    allowed = {"store", "read", "exists", "delete"}
    public = {name for name in vars(PrivateObjectService) if not name.startswith("_")}
    assert public == allowed

    for name in allowed:
        parameters = inspect.signature(getattr(PrivateObjectService, name)).parameters
        assert set(parameters) <= {"self", "scope", "data", "object_id"}, name
        if "object_id" in parameters:
            assert parameters["object_id"].annotation is uuid.UUID


@pytest.mark.parametrize(
    "untrusted",
    [
        COMPANY_A,
        str(COMPANY_A),
        AuthenticatedCompanyContext(
            user_id=uuid.uuid4(),
            company_id=COMPANY_A,
            membership_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
        ),
    ],
)
def test_service_requires_a_company_scope(service: PrivateObjectService, untrusted: object) -> None:
    with pytest.raises(StorageError):
        service.store(untrusted, b"data")  # type: ignore[arg-type]
    with pytest.raises(StorageError):
        service.read(untrusted, uuid.uuid4())  # type: ignore[arg-type]


def test_unconfigured_storage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_dependencies, "get_private_object_storage", lambda: None)

    with pytest.raises(StorageConfigurationError):
        get_private_object_service()


def test_application_exposes_no_static_or_file_routes() -> None:
    from starlette.routing import Mount

    from app.main import app

    assert not [route for route in app.routes if isinstance(route, Mount)]
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not [path for path in paths if "object" in path or "file" in path]


# HTTP level (test-only routes) -------------------------------------------------


@pytest.fixture
def http(
    session_factory: sessionmaker[Session],  # noqa: F811
    development_provider: DevelopmentAuthenticationProvider,  # noqa: F811
    service: PrivateObjectService,
) -> TestClient:
    app = FastAPI()

    @app.post("/companies/{company_id}/objects", status_code=201)
    def store(
        scope: CompanyDb, objects: ObjectStorage, data: Annotated[bytes, Body()]
    ) -> dict[str, str]:
        return {"object_id": str(objects.store(scope, data))}

    @app.get("/companies/{company_id}/objects/{object_id}")
    def read(object_id: uuid.UUID, scope: CompanyDb, objects: ObjectStorage) -> Response:
        try:
            return Response(objects.read(scope, object_id), media_type="application/octet-stream")
        except ObjectNotFoundError:
            raise HTTPException(404, "Not found") from None

    @app.delete("/companies/{company_id}/objects/{object_id}", status_code=204)
    def delete(object_id: uuid.UUID, scope: CompanyDb, objects: ObjectStorage) -> None:
        if not objects.delete(scope, object_id):
            raise HTTPException(404, "Not found")

    def _db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: development_provider
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_private_object_service] = lambda: service
    return TestClient(app)


def auth(subject: str) -> dict[str, str]:
    token = issue_development_token(
        environment="development", secret=TEST_DEV_SECRET, subject=subject
    )
    return {"Authorization": f"Bearer {token}"}


def test_http_objects_isolated_by_membership(
    http: TestClient,
    seed: SeedData,  # noqa: F811
    service: PrivateObjectService,
) -> None:
    alice, bob = auth("alice-subject"), auth("bob-subject")
    a_url, b_url = f"/companies/{seed.company_a}/objects", f"/companies/{seed.company_b}/objects"

    object_a = http.post(a_url, content=b"A bytes", headers=alice).json()["object_id"]
    object_b = http.post(b_url, content=b"B bytes", headers=bob).json()["object_id"]

    assert http.get(f"{a_url}/{object_a}", headers=alice).content == b"A bytes"
    assert http.get(f"{b_url}/{object_b}", headers=bob).content == b"B bytes"

    # Alice knows B's object ID. In her own Company it is simply not found ...
    assert http.get(f"{a_url}/{object_b}", headers=alice).status_code == 404
    assert http.delete(f"{a_url}/{object_b}", headers=alice).status_code == 404
    # ... and B's Company is refused outright (no Membership).
    assert http.get(f"{b_url}/{object_b}", headers=alice).status_code == 403
    assert http.delete(f"{b_url}/{object_b}", headers=alice).status_code == 403
    assert http.post(b_url, content=b"intrusion", headers=alice).status_code == 403
    # Symmetric for Bob.
    assert http.get(f"{b_url}/{object_a}", headers=bob).status_code == 404
    assert http.get(f"{a_url}/{object_a}", headers=bob).status_code == 403

    assert service.read(scope(seed.company_b), uuid.UUID(object_b)) == b"B bytes"
    assert service.read(scope(seed.company_a), uuid.UUID(object_a)) == b"A bytes"
    assert http.delete(f"{a_url}/{object_a}", headers=alice).status_code == 204
    assert http.get(f"{a_url}/{object_a}", headers=alice).status_code == 404


def test_http_client_supplied_company_is_ignored(
    http: TestClient,
    seed: SeedData,  # noqa: F811
    service: PrivateObjectService,
) -> None:
    response = http.post(
        f"/companies/{seed.company_a}/objects?company_id={seed.company_b}",
        content=b"A bytes",
        headers={**auth("alice-subject"), "X-Company-ID": str(seed.company_b)},
    )
    object_id = uuid.UUID(response.json()["object_id"])

    assert service.exists(scope(seed.company_a), object_id)
    assert not service.exists(scope(seed.company_b), object_id)


@pytest.mark.parametrize(
    "object_ref",
    [
        "..%2F..%2Fetc%2Fpasswd",
        "%2e%2e%2f%2e%2e%2fsecret",
        "..",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_http_unsafe_object_references_never_resolve(
    http: TestClient,
    seed: SeedData,  # noqa: F811
    object_ref: str,
) -> None:
    response = http.get(
        f"/companies/{seed.company_a}/objects/{object_ref}", headers=auth("alice-subject")
    )

    assert response.status_code in {404, 422}
    assert b"root:" not in response.content


def test_http_unauthenticated_object_access_rejected(
    http: TestClient,
    seed: SeedData,  # noqa: F811
    service: PrivateObjectService,
) -> None:
    object_a = service.store(scope(seed.company_a), b"A bytes")

    response = http.get(f"/companies/{seed.company_a}/objects/{object_a}")

    assert response.status_code == 401
    assert b"A bytes" not in response.content


@pytest.mark.parametrize(
    "object_id", [uuid.UUID(int=0), "../../secret", f"companies/{COMPANY_A}/x", None]
)
def test_invalid_object_ids_behave_as_missing(
    service: PrivateObjectService, object_id: object
) -> None:
    with pytest.raises(ObjectNotFoundError):
        service.read(scope(COMPANY_A), object_id)  # type: ignore[arg-type]
    assert service.exists(scope(COMPANY_A), object_id) is False  # type: ignore[arg-type]
    assert service.delete(scope(COMPANY_A), object_id) is False  # type: ignore[arg-type]
