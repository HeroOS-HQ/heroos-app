"""Configuration fails closed: the development provider cannot run outside development."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.auth.exceptions import AuthenticationConfigurationError
from app.auth.providers import build_authentication_provider
from app.auth.providers.cognito import CognitoAccessTokenProvider
from app.auth.providers.development import DevelopmentAuthenticationProvider
from app.core.config import Settings

API_ROOT = Path(__file__).resolve().parents[2]
DEV_SECRET = "settings-test-development-secret-0123456789"
COGNITO = {
    "heroos_auth_provider": "cognito",
    "heroos_cognito_issuer": "https://cognito-idp.test.invalid/test-user-pool",
    "heroos_cognito_app_client_id": "test-app-client-id",
}


def make_settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_development_provider_allowed_in_development() -> None:
    settings = make_settings(
        heroos_env="development",
        heroos_auth_provider="development",
        heroos_dev_auth_secret=DEV_SECRET,
    )

    assert isinstance(build_authentication_provider(settings), DevelopmentAuthenticationProvider)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_development_provider_rejected_outside_development(environment: str) -> None:
    with pytest.raises(ValidationError, match="must be 'cognito'") as exc_info:
        make_settings(
            heroos_env=environment,
            heroos_auth_provider="development",
            heroos_dev_auth_secret=DEV_SECRET,
        )

    assert DEV_SECRET not in str(exc_info.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_dev_secret_rejected_outside_development_even_with_cognito(environment: str) -> None:
    with pytest.raises(ValidationError, match="HEROOS_DEV_AUTH_SECRET must not be set"):
        make_settings(heroos_env=environment, heroos_dev_auth_secret=DEV_SECRET, **COGNITO)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_require_an_auth_provider(environment: str) -> None:
    with pytest.raises(ValidationError, match="must be 'cognito'"):
        make_settings(heroos_env=environment)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_accept_cognito(environment: str) -> None:
    settings = make_settings(heroos_env=environment, **COGNITO)

    assert isinstance(build_authentication_provider(settings), CognitoAccessTokenProvider)


def test_unknown_environment_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(heroos_env="Production")


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_development_provider_requires_strong_secret(secret: str | None) -> None:
    with pytest.raises(ValidationError, match="HEROOS_DEV_AUTH_SECRET must be at least"):
        make_settings(heroos_auth_provider="development", heroos_dev_auth_secret=secret)


@pytest.mark.parametrize(
    "overrides",
    [
        {"heroos_cognito_issuer": None},
        {"heroos_cognito_app_client_id": None},
        {"heroos_cognito_issuer": "http://cognito-idp.test.invalid/test-user-pool"},
        {"heroos_cognito_issuer": "https://cognito-idp.test.invalid/test-user-pool/"},
        {"heroos_cognito_jwks_uri": "http://jwks.test.invalid/jwks.json"},
    ],
)
def test_incomplete_or_insecure_cognito_configuration_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{**COGNITO, **overrides})


def test_cognito_jwks_uri_derived_from_issuer() -> None:
    settings = make_settings(**COGNITO)

    assert settings.cognito_jwks_uri == (
        "https://cognito-idp.test.invalid/test-user-pool/.well-known/jwks.json"
    )


def test_no_provider_configured_in_development_builds_none() -> None:
    assert build_authentication_provider(make_settings()) is None


def test_provider_factory_rechecks_environment_when_validation_is_skipped() -> None:
    settings = Settings.model_construct(
        heroos_env="production",
        heroos_auth_provider="development",
        heroos_dev_auth_secret=make_settings(
            heroos_auth_provider="development", heroos_dev_auth_secret=DEV_SECRET
        ).heroos_dev_auth_secret,
    )

    with pytest.raises(AuthenticationConfigurationError):
        build_authentication_provider(settings)


def test_secrets_not_exposed_by_settings_repr() -> None:
    settings = make_settings(heroos_auth_provider="development", heroos_dev_auth_secret=DEV_SECRET)

    assert DEV_SECRET not in repr(settings)
    assert DEV_SECRET not in str(settings.model_dump())


def test_validation_errors_do_not_echo_configuration_values() -> None:
    database_url = "postgresql+psycopg://heroos:do-not-leak-password@db.invalid/heroos"
    with pytest.raises(ValidationError) as exc_info:
        make_settings(
            heroos_env="production",
            heroos_auth_provider="development",
            heroos_dev_auth_secret=DEV_SECRET,
            database_url=database_url,
        )

    assert DEV_SECRET not in str(exc_info.value)
    assert "do-not-leak-password" not in str(exc_info.value)


def _import_app(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean_env = {
        name: value for name, value in os.environ.items() if not name.startswith("HEROOS_")
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env={**clean_env, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_application_startup_fails_with_development_provider_outside_development(
    environment: str,
) -> None:
    result = _import_app(
        {
            "HEROOS_ENV": environment,
            "HEROOS_AUTH_PROVIDER": "development",
            "HEROOS_DEV_AUTH_SECRET": DEV_SECRET,
        }
    )

    assert result.returncode != 0
    assert "HEROOS_AUTH_PROVIDER must be 'cognito'" in result.stderr
    assert DEV_SECRET not in result.stderr + result.stdout


def test_application_starts_with_development_provider_in_development() -> None:
    result = _import_app(
        {
            "HEROOS_ENV": "development",
            "HEROOS_AUTH_PROVIDER": "development",
            "HEROOS_DEV_AUTH_SECRET": DEV_SECRET,
        }
    )

    assert result.returncode == 0, result.stderr
