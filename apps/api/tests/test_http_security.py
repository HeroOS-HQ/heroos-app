"""CORS allow-list validation and behaviour, security headers and API docs exposure.

Uses ``create_app`` with explicit settings; no database, network or AWS. Only
``/health`` is exercised, so no dependency needs overriding.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, parse_cors_origins
from app.main import create_app

COGNITO = {
    "heroos_auth_provider": "cognito",
    "heroos_cognito_issuer": "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_TEST",
    "heroos_cognito_app_client_id": "test-app-client-id",
}
DEPLOYED_DATABASE_URL = "postgresql+psycopg://heroos_app@db.test.invalid/heroos"
WEB_ORIGIN = "https://heroos-demo.example.com"


def make_settings(environment: str = "staging", **values: Any) -> Settings:
    if environment != "development":
        values = {**COGNITO, "database_url": DEPLOYED_DATABASE_URL, **values}
    return Settings(_env_file=None, heroos_env=environment, **values)  # type: ignore[call-arg]


def client_for(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


# --- Allow-list validation ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ()),
        ("", ()),
        (" , ", ()),
        (WEB_ORIGIN, (WEB_ORIGIN,)),
        (
            f"{WEB_ORIGIN}, https://other.example.com:8443",
            (WEB_ORIGIN, "https://other.example.com:8443"),
        ),
        (f"{WEB_ORIGIN},{WEB_ORIGIN}", (WEB_ORIGIN,)),
    ],
)
def test_valid_origins_parsed(raw: str | None, expected: tuple[str, ...]) -> None:
    assert parse_cors_origins(raw, "staging") == expected


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "https://*.example.com",
        "https://heroos-demo.example.com/",
        "https://heroos-demo.example.com/app",
        "https://heroos-demo.example.com?x=1",
        "https://heroos-demo.example.com#frag",
        "https://user:pass@heroos-demo.example.com",
        "https://HeroOS-Demo.example.com",
        "http://heroos-demo.example.com",
        "http://localhost:3000",
        "null",
        "heroos-demo.example.com",
        "ftp://heroos-demo.example.com",
    ],
)
def test_unsafe_origins_rejected_outside_development(raw: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        make_settings(heroos_cors_allowed_origins=raw)
    assert "HEROOS_CORS_ALLOWED_ORIGINS" in str(exc_info.value)


def test_plain_http_localhost_allowed_only_in_development() -> None:
    development = make_settings("development", heroos_cors_allowed_origins="http://localhost:3000")
    assert development.cors_allowed_origins == ("http://localhost:3000",)
    with pytest.raises(ValidationError):
        make_settings("development", heroos_cors_allowed_origins="http://example.com")


def test_validation_error_does_not_echo_the_value() -> None:
    marker = "https://secret-marker.example.com/path"
    with pytest.raises(ValidationError) as exc_info:
        make_settings(heroos_cors_allowed_origins=marker)
    assert marker not in str(exc_info.value)


# --- CORS behaviour -----------------------------------------------------------


def test_no_cors_headers_when_no_origin_is_configured() -> None:
    client = client_for(make_settings())
    simple = client.get("/health", headers={"Origin": WEB_ORIGIN})
    preflight = client.options(
        "/health",
        headers={"Origin": WEB_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert simple.status_code == 200
    assert "access-control-allow-origin" not in simple.headers
    assert "access-control-allow-origin" not in preflight.headers


def test_allowed_origin_gets_get_only_without_credentials() -> None:
    client = client_for(make_settings(heroos_cors_allowed_origins=WEB_ORIGIN))
    preflight = client.options(
        "/health",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert preflight.headers["access-control-allow-methods"] == "GET"
    # Starlette always lists the CORS-safelisted headers (browsers send those
    # without permission anyway); the only non-safelisted header is Authorization.
    allowed = {
        h.strip().lower() for h in preflight.headers["access-control-allow-headers"].split(",")
    }
    assert allowed == {
        "accept",
        "accept-language",
        "content-language",
        "content-type",
        "authorization",
    }
    assert "access-control-allow-credentials" not in preflight.headers

    simple = client.get("/health", headers={"Origin": WEB_ORIGIN})
    assert simple.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert "access-control-allow-credentials" not in simple.headers


@pytest.mark.parametrize(
    "origin", ["https://evil.example.com", "https://heroos-demo.example.com.evil.com", "null"]
)
def test_other_origins_get_no_cors_grant(origin: str) -> None:
    client = client_for(make_settings(heroos_cors_allowed_origins=WEB_ORIGIN))
    simple = client.get("/health", headers={"Origin": origin})
    preflight = client.options(
        "/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )

    assert "access-control-allow-origin" not in simple.headers
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_preflight_for_write_methods_rejected(method: str) -> None:
    client = client_for(make_settings(heroos_cors_allowed_origins=WEB_ORIGIN))
    preflight = client.options(
        "/health", headers={"Origin": WEB_ORIGIN, "Access-Control-Request-Method": method}
    )

    assert preflight.status_code == 400


def test_preflight_for_other_request_headers_rejected() -> None:
    client = client_for(make_settings(heroos_cors_allowed_origins=WEB_ORIGIN))
    preflight = client.options(
        "/health",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-company-id",
        },
    )

    assert preflight.status_code == 400


# --- Security headers and docs ------------------------------------------------


def test_security_headers_on_every_response() -> None:
    client = client_for(make_settings())
    for response in (client.get("/health"), client.get("/does-not-exist")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"].startswith("default-src 'none'")
        assert response.headers["strict-transport-security"] == "max-age=63072000"
        assert response.headers["x-request-id"]


def test_development_omits_deployed_only_headers() -> None:
    response = client_for(make_settings("development")).get("/health")

    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers
    assert "content-security-policy" not in response.headers


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_api_docs_not_published_in_deployed_environments(environment: str) -> None:
    client = client_for(make_settings(environment))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_api_docs_available_in_development() -> None:
    client = client_for(make_settings("development"))
    assert client.get("/openapi.json").status_code == 200
