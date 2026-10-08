"""Sensitive-data leakage: synthetic canaries must never reach logs or responses.

Every scenario sends the same unmistakable test-only canaries through headers,
cookies, the query string, the path and the body, over the real dependency chain
(bearer token -> User -> Membership -> CompanyScope -> storage) with the
production log formatter at DEBUG. Then it asserts no canary appears in:

- the formatted JSON log output,
- any raw log record (message, args or attributes),
- the response body or headers, including request and error IDs.

Opaque internal IDs (request, error, Company, User) may be logged by design.
"""

import json
import os
import subprocess
import sys
import traceback
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Body, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import CompanyContext, get_authentication_provider
from app.auth.providers.development import (
    DevelopmentAuthenticationProvider,
    issue_development_token,
)
from app.core.config import Settings
from app.db.session import get_db
from app.observability import install_observability
from app.storage.dependencies import ObjectStorage, get_private_object_service
from app.storage.errors import ObjectNotFoundError
from app.storage.keys import StorageKey
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
from tests.observability.conftest import CapturedLogs, raw_record_text

BEARER_CANARY = "SUPER_SECRET_BEARER_CANARY"
PASSWORD_CANARY = "SUPER_SECRET_PASSWORD_CANARY"
COOKIE_CANARY = "SUPER_SECRET_COOKIE_CANARY"
API_KEY_CANARY = "SUPER_SECRET_API_KEY_CANARY"
EMPLOYEE_CANARY = "SENSITIVE_EMPLOYEE_NAME_CANARY"
NARRATIVE_CANARY = "SENSITIVE_CASE_NARRATIVE_CANARY"
DOCUMENT_CANARY = "SENSITIVE_DOCUMENT_BODY_CANARY"
QUERY_CANARY = "SENSITIVE_QUERY_CANARY"
STORAGE_PATH_CANARY = "SENSITIVE_STORAGE_PATH_CANARY"

CANARIES = (
    BEARER_CANARY,
    PASSWORD_CANARY,
    COOKIE_CANARY,
    API_KEY_CANARY,
    EMPLOYEE_CANARY,
    NARRATIVE_CANARY,
    DOCUMENT_CANARY,
    QUERY_CANARY,
    STORAGE_PATH_CANARY,
)

SENSITIVE_QUERY = {"employee": QUERY_CANARY, "password": PASSWORD_CANARY}
SENSITIVE_BODY = {
    "employee_name": EMPLOYEE_CANARY,
    "narrative": NARRATIVE_CANARY,
    "password": PASSWORD_CANARY,
}


class CaseInput(BaseModel):
    employee_name: str
    narrative: str
    severity: int


@dataclass
class Harness:
    client: TestClient
    seed: SeedData
    alice_token: str
    carol_token: str
    service: PrivateObjectService
    storage_root: Path


@pytest.fixture
def harness(
    tmp_path: Path,
    session_factory: sessionmaker[Session],  # noqa: F811
    seed: SeedData,  # noqa: F811
    development_provider: DevelopmentAuthenticationProvider,  # noqa: F811
) -> Harness:
    storage_root = tmp_path / STORAGE_PATH_CANARY / "objects"
    service = PrivateObjectService(LocalFilesystemStorage(storage_root, environment="development"))
    app = FastAPI()
    install_observability(app)

    @app.post("/companies/{company_id}/cases")
    def create_case(context: CompanyContext, case: CaseInput) -> dict[str, str]:
        return {"status": "accepted"}

    @app.post("/companies/{company_id}/cases/explode")
    def explode(context: CompanyContext, body: Annotated[dict[str, Any], Body()]) -> None:
        # A careless failure whose message carries request content.
        raise RuntimeError(
            f"could not process {body['employee_name']}: {body['narrative']} ({body['password']})"
        )

    @app.get("/companies/{company_id}/documents/{object_id}")
    def read_document(
        object_id: uuid.UUID, scope: CompanyDb, objects: ObjectStorage
    ) -> dict[str, int]:
        try:
            return {"size": len(objects.read(scope, object_id))}
        except ObjectNotFoundError:
            raise HTTPException(404, "Not found") from None

    def _db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_authentication_provider] = lambda: development_provider
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_private_object_service] = lambda: service

    def token(subject: str) -> str:
        return issue_development_token(
            environment="development", secret=TEST_DEV_SECRET, subject=subject
        )

    return Harness(
        client=TestClient(app),
        seed=seed,
        alice_token=token("alice-subject"),
        carol_token=token("carol-subject"),
        service=service,
        storage_root=storage_root,
    )


def sensitive_headers(token: str = BEARER_CANARY) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Cookie": f"session={COOKIE_CANARY}; csrftoken={PASSWORD_CANARY}",
        "X-Api-Key": API_KEY_CANARY,
        "X-Request-ID": BEARER_CANARY,
        "X-Employee-Name": EMPLOYEE_CANARY,
    }


def assert_no_leak(
    response: httpx.Response,
    logs: CapturedLogs,
    caplog: pytest.LogCaptureFixture,
    *secrets: str,
) -> None:
    surfaces = {
        "formatted logs": logs.text,
        "raw log records": raw_record_text(caplog),
        "response body": response.text,
        "response headers": json.dumps(dict(response.headers)),
    }
    for canary in (*CANARIES, *secrets):
        for surface, content in surfaces.items():
            assert canary not in content, f"{canary[:40]} leaked into {surface}"
    # Logs are still produced and correlated: the protection is redaction, not silence.
    (completed,) = logs.events("request_completed")
    assert completed["request_id"] == response.headers["X-Request-ID"]


def test_successful_request(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.post(
        f"/companies/{harness.seed.company_a}/cases",
        params=SENSITIVE_QUERY,
        json={**SENSITIVE_BODY, "severity": 2},
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 200
    assert_no_leak(response, logs, caplog, harness.alice_token)
    # The token's signature segment is a credential on its own.
    assert harness.alice_token.rsplit(".", 1)[-1] not in logs.text
    (completed,) = logs.events("request_completed")
    assert completed["route"] == "/companies/{company_id}/cases"
    assert completed["company_id"] == str(harness.seed.company_a)
    assert completed["user_id"] == str(harness.seed.alice)


def test_authentication_failure(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.post(
        f"/companies/{harness.seed.company_a}/cases",
        params=SENSITIVE_QUERY,
        json={**SENSITIVE_BODY, "severity": 2},
        headers=sensitive_headers(),
    )

    assert response.status_code == 401
    assert_no_leak(response, logs, caplog)


def test_authorization_failure(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.post(
        f"/companies/{harness.seed.company_a}/cases",
        params=SENSITIVE_QUERY,
        json={**SENSITIVE_BODY, "severity": 2},
        headers=sensitive_headers(harness.carol_token),
    )

    assert response.status_code == 403
    assert_no_leak(response, logs, caplog, harness.carol_token)
    # A denied request never records the requested Company as authorized.
    (completed,) = logs.events("request_completed")
    assert "company_id" not in completed and "user_id" not in completed


def test_validation_failure(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.post(
        f"/companies/{harness.seed.company_a}/cases",
        params=SENSITIVE_QUERY,
        json={**SENSITIVE_BODY, "severity": f"{NARRATIVE_CANARY} is not a number"},
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 422
    assert_no_leak(response, logs, caplog, harness.alice_token)


def test_not_found_route(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.get(
        f"/companies/{harness.seed.company_a}/employees/{EMPLOYEE_CANARY}",
        params=SENSITIVE_QUERY,
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 404
    assert_no_leak(response, logs, caplog, harness.alice_token)


def test_unhandled_application_error(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    response = harness.client.post(
        f"/companies/{harness.seed.company_a}/cases/explode",
        params=SENSITIVE_QUERY,
        json=SENSITIVE_BODY,
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 500
    assert_no_leak(response, logs, caplog, harness.alice_token)
    (error,) = logs.events("unhandled_exception")
    assert error["exception_type"] == "RuntimeError"
    assert error["error_id"] == response.json()["error_id"]


def test_storage_failure(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    object_id = uuid.uuid4()
    # Corrupt storage: a directory where the object file belongs.
    key = StorageKey.for_object(harness.seed.company_a, object_id)
    harness.storage_root.joinpath(*key.parts).mkdir(parents=True)

    response = harness.client.get(
        f"/companies/{harness.seed.company_a}/documents/{object_id}",
        params=SENSITIVE_QUERY,
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 500
    assert_no_leak(response, logs, caplog, harness.alice_token, str(harness.storage_root))
    (error,) = logs.events("unhandled_exception")
    assert error["exception_type"] == "app.storage.errors.StorageError"


def test_storage_read_and_cross_company_miss(
    harness: Harness, logs: CapturedLogs, caplog: pytest.LogCaptureFixture
) -> None:
    scope_b = CompanyScope(session=Session(), company_id=harness.seed.company_b)
    object_b = harness.service.store(scope_b, DOCUMENT_CANARY.encode())

    response = harness.client.get(
        f"/companies/{harness.seed.company_a}/documents/{object_b}",
        params=SENSITIVE_QUERY,
        headers=sensitive_headers(harness.alice_token),
    )

    assert response.status_code == 404
    assert_no_leak(response, logs, caplog, harness.alice_token, str(harness.storage_root))


def test_configuration_validation_error() -> None:
    database_url = f"postgresql+psycopg://heroos_app:{PASSWORD_CANARY}@db.invalid/heroos"
    with pytest.raises(ValidationError) as exc_info:
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            heroos_env="production",
            heroos_auth_provider="development",
            heroos_dev_auth_secret=API_KEY_CANARY * 2,
            heroos_local_storage_root=f"/srv/{STORAGE_PATH_CANARY}",
            database_url=database_url,
        )

    error = exc_info.value
    # What HeroOS emits for configuration errors: the startup traceback (str/repr).
    emitted = "".join(traceback.format_exception(error)) + repr(error)
    # Pydantic keeps the raw input in errors()/json() unless include_input=False;
    # any future serialization of a ValidationError must pass that flag.
    serialized = f"{error.errors(include_input=False)!r} {error.json(include_input=False)}"
    for canary in CANARIES:
        assert canary not in emitted
        assert canary not in serialized


def test_startup_configuration_failure_output() -> None:
    api_root = Path(__file__).resolve().parents[2]
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HEROOS_") and name not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=api_root,
        env={
            **clean,
            "HEROOS_ENV": "development",
            "HEROOS_STORAGE_PROVIDER": "local",
            "HEROOS_LOCAL_STORAGE_ROOT": f"relative/{STORAGE_PATH_CANARY}",
            "HEROOS_DEV_AUTH_SECRET": API_KEY_CANARY * 2,
            "HEROOS_AUTH_PROVIDER": "development",
            "DATABASE_URL": f"postgresql+psycopg://heroos_app:{PASSWORD_CANARY}@db.invalid/x",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "HEROOS_LOCAL_STORAGE_ROOT must be an absolute path" in result.stderr
    for canary in CANARIES:
        assert canary not in result.stdout + result.stderr
