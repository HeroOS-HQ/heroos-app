"""Structured logging, request correlation and the unhandled-error boundary."""

import json
import logging
import re
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from app.observability import install_observability
from app.observability.logging import StructuredFormatter, configure_logging
from app.observability.middleware import REQUEST_ID_HEADER, UNMATCHED_ROUTE
from tests.observability.conftest import CapturedLogs

REQUEST_ID = re.compile(r"[0-9a-f]{32}")


class Item(BaseModel):
    name: str
    quantity: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_observability(app)

    @app.get("/items/{item_id}")
    def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.post("/items")
    def create_item(item: Item) -> dict[str, str]:
        return {"name": item.name}

    @app.get("/forbidden")
    def forbidden() -> None:
        raise HTTPException(403, "Forbidden")

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("database said: secret detail")

    @app.get("/explode-async")
    async def explode_async() -> None:
        raise ValueError("async failure detail")

    @app.get("/explode-midstream")
    def explode_midstream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            yield b"partial"
            raise RuntimeError("midstream failure detail")

        return StreamingResponse(body())

    return TestClient(app)


def is_heroos_handler(handler: logging.Handler) -> bool:
    return isinstance(handler.formatter, StructuredFormatter)


def record(**kwargs: Any) -> logging.LogRecord:
    defaults: dict[str, Any] = {
        "name": "app.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "message",
        "args": None,
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)


# Formatter ---------------------------------------------------------------------


def test_formatter_emits_one_json_object_with_allowlisted_fields() -> None:
    entry = record(msg="request_completed")
    entry.event = "request_completed"
    entry.status_code = 200
    entry.route = "/items/{item_id}"
    entry.authorization = "Bearer must-not-appear"
    entry.body = "must-not-appear"

    payload = json.loads(StructuredFormatter().format(entry))

    assert payload["event"] == "request_completed"
    assert payload["status_code"] == 200
    assert payload["route"] == "/items/{item_id}"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload and "logger" in payload
    assert "must-not-appear" not in json.dumps(payload)


def test_formatter_never_renders_exception_messages_or_full_paths() -> None:
    try:
        raise KeyError("exception message detail")
    except KeyError:
        entry = record(msg="failure", exc_info=sys.exc_info(), stack_info="stack detail")

    line = StructuredFormatter().format(entry)
    payload = json.loads(line)

    assert "exception message detail" not in line
    assert "stack detail" not in line
    assert "Traceback" not in line
    assert payload["exception_type"] == "KeyError"
    frame = payload["exception_frames"][-1]
    assert frame == {
        "file": "test_structured_logging.py",
        "line": frame["line"],
        "function": "test_formatter_never_renders_exception_messages_or_full_paths",
    }
    assert "/" not in json.dumps(payload["exception_frames"])


def test_formatter_reports_exception_chain_types_only() -> None:
    try:
        try:
            raise OSError("inner detail")
        except OSError as inner:
            raise RuntimeError("outer detail") from inner
    except RuntimeError:
        entry = record(exc_info=sys.exc_info())

    line = StructuredFormatter().format(entry)

    assert json.loads(line)["exception_chain"] == ["OSError"]
    assert "detail" not in line


def test_configure_logging_is_idempotent_and_quiets_risky_loggers(logs: CapturedLogs) -> None:
    configured = [h for h in logging.getLogger().handlers if is_heroos_handler(h)]

    assert len(configured) == 1
    assert logging.getLogger("uvicorn.access").disabled
    for name in ("sqlalchemy", "sqlalchemy.engine", "httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


def test_sqlalchemy_never_logs_sql_or_parameters_at_debug(logs: CapturedLogs) -> None:
    engine = create_engine("sqlite+pysqlite://")
    with engine.connect() as connection:
        connection.execute(text("SELECT :value"), {"value": "SQL_PARAMETER_CANARY"})

    assert "SQL_PARAMETER_CANARY" not in logs.text
    assert "SELECT" not in logs.text


# Request correlation and request_completed --------------------------------------


def test_request_id_generated_returned_and_logged(client: TestClient, logs: CapturedLogs) -> None:
    first = client.get("/items/1")
    second = client.get("/items/2")

    ids = [first.headers[REQUEST_ID_HEADER], second.headers[REQUEST_ID_HEADER]]
    assert all(REQUEST_ID.fullmatch(request_id) for request_id in ids)
    assert ids[0] != ids[1]
    assert [event["request_id"] for event in logs.events("request_completed")] == ids


def test_client_supplied_request_id_is_ignored(client: TestClient, logs: CapturedLogs) -> None:
    response = client.get("/items/1", headers={REQUEST_ID_HEADER: "client-chosen-id\nforged"})

    assert REQUEST_ID.fullmatch(response.headers[REQUEST_ID_HEADER])
    assert "client-chosen-id" not in logs.text


def test_request_completed_uses_route_template_not_raw_path(
    client: TestClient, logs: CapturedLogs
) -> None:
    client.get("/items/424242?employee=Jane")

    (event,) = logs.events("request_completed")
    assert event["route"] == "/items/{item_id}"
    assert event["method"] == "GET"
    assert event["status_code"] == 200
    assert isinstance(event["duration_ms"], float)
    assert "424242" not in logs.text and "Jane" not in logs.text


def test_unmatched_route_logs_no_path(client: TestClient, logs: CapturedLogs) -> None:
    response = client.get("/no/such/path/John-Smith?q=1")

    assert response.status_code == 404
    (event,) = logs.events("request_completed")
    assert event["route"] == UNMATCHED_ROUTE
    assert "John-Smith" not in logs.text


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [("GET", "/forbidden", 403), ("GET", "/items/not-an-int", 422), ("GET", "/missing", 404)],
)
def test_expected_client_errors_are_not_error_events(
    client: TestClient, logs: CapturedLogs, method: str, path: str, status: int
) -> None:
    response = client.request(method, path)

    assert response.status_code == status
    assert logs.events("unhandled_exception") == []
    (event,) = logs.events("request_completed")
    assert event["status_code"] == status
    assert event["level"] == "INFO"


def test_validation_errors_do_not_echo_submitted_values(
    client: TestClient, logs: CapturedLogs
) -> None:
    response = client.post("/items", json={"name": "VALIDATION_INPUT_CANARY", "quantity": "x"})

    assert response.status_code == 422
    assert "VALIDATION_INPUT_CANARY" not in response.text
    (error,) = response.json()["detail"]
    assert set(error) == {"type", "loc", "msg"}
    assert error["loc"] == ["body", "quantity"]


# Unhandled-error boundary -----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "exception_type"),
    [("/explode", "RuntimeError"), ("/explode-async", "ValueError")],
)
def test_unhandled_exception_returns_generic_500_and_sanitized_event(
    client: TestClient, logs: CapturedLogs, path: str, exception_type: str
) -> None:
    response = client.get(path)

    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"detail", "request_id", "error_id"}
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert REQUEST_ID.fullmatch(body["error_id"])
    assert "detail" not in response.text.replace('"detail"', "")

    (error,) = logs.events("unhandled_exception")
    assert error["level"] == "ERROR"
    assert error["error_id"] == body["error_id"]
    assert error["request_id"] == body["request_id"]
    assert error["exception_type"] == exception_type
    assert error["route"] == path
    assert error["exception_frames"][-1]["file"] == "test_structured_logging.py"
    (completed,) = logs.events("request_completed")
    assert completed["status_code"] == 500
    assert "failure detail" not in logs.text and "secret detail" not in logs.text
    assert "Traceback" not in logs.text


def test_exception_after_response_started_is_logged_not_reraised(
    client: TestClient, logs: CapturedLogs
) -> None:
    client.get("/explode-midstream")

    (error,) = logs.events("unhandled_exception")
    assert error["exception_type"] == "RuntimeError"
    assert "midstream failure detail" not in logs.text


def test_application_wires_logging_and_observability() -> None:
    from app.main import app
    from app.observability.middleware import RequestObservabilityMiddleware

    assert any(m.cls is RequestObservabilityMiddleware for m in app.user_middleware)
    response = TestClient(app).get("/health")
    assert REQUEST_ID.fullmatch(response.headers[REQUEST_ID_HEADER])


def test_official_startup_command_disables_raw_access_log() -> None:
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    (command,) = re.findall(r"^CMD (.+)$", dockerfile, flags=re.MULTILINE)
    assert "uvicorn" in command and "--no-access-log" in command


def test_configure_logging_replaces_only_its_own_handler() -> None:
    root = logging.getLogger()
    others = [h for h in root.handlers if not is_heroos_handler(h)]
    first = configure_logging("INFO")
    second = configure_logging("INFO")
    try:
        assert first not in root.handlers
        assert [h for h in root.handlers if is_heroos_handler(h)] == [second]
        # Other handlers (pytest capture, a platform agent) are left alone.
        assert [h for h in root.handlers if not is_heroos_handler(h)] == others
    finally:
        root.removeHandler(second)
