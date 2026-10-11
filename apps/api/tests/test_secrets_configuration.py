"""Secrets and configuration hygiene.

Secret configuration is consumed only through ``Settings`` / ``DatabaseSettings``,
never printed, and deployed environments refuse local development fallbacks.
"""

import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.database_settings import DatabaseConfigurationError, DatabaseSettings

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]

PASSWORD_CANARY = "SUPER_SECRET_PASSWORD_CANARY"
RUNTIME_URL = f"postgresql+psycopg://heroos_app:{PASSWORD_CANARY}@db.test.invalid/heroos"
MIGRATION_URL = f"postgresql+psycopg://heroos:{PASSWORD_CANARY}@db.test.invalid/heroos"
COGNITO = {
    "heroos_auth_provider": "cognito",
    "heroos_cognito_issuer": "https://cognito-idp.test.invalid/test-user-pool",
    "heroos_cognito_app_client_id": "test-app-client-id",
}


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("HEROOS_") or name in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}:
            monkeypatch.delenv(name)


def make_settings(**values: Any) -> Settings:
    values.setdefault("heroos_env", "development")
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_database_urls_never_rendered() -> None:
    settings = make_settings(database_url=RUNTIME_URL, migration_database_url=MIGRATION_URL)

    for rendered in (
        repr(settings),
        str(settings),
        str(settings.model_dump()),
        settings.model_dump_json(),
        repr(DatabaseSettings(_env_file=None, migration_database_url=MIGRATION_URL)),  # type: ignore[call-arg]
    ):
        assert PASSWORD_CANARY not in rendered
    # Still available where a driver needs it.
    assert settings.require_database_url() == RUNTIME_URL


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_requires_explicit_database_url(environment: str) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must be explicitly configured"):
        make_settings(heroos_env=environment, **COGNITO)


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_deployed_environment_refuses_local_development_database(
    environment: str, host: str
) -> None:
    url = f"postgresql+psycopg://heroos_app:{PASSWORD_CANARY}@{host}:5433/heroos"
    with pytest.raises(ValidationError, match="must not name a local development database") as e:
        make_settings(heroos_env=environment, database_url=url, **COGNITO)

    assert PASSWORD_CANARY not in str(e.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_rejects_unparseable_database_url_without_echo(
    environment: str,
) -> None:
    with pytest.raises(ValidationError, match="not a valid database URL") as e:
        make_settings(heroos_env=environment, database_url=f"::{PASSWORD_CANARY}::", **COGNITO)

    rendered = "".join(traceback.format_exception(e.value))
    assert PASSWORD_CANARY not in rendered


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_api_never_receives_migration_credential_outside_development(environment: str) -> None:
    with pytest.raises(ValidationError, match="MIGRATION_DATABASE_URL must not be provided") as e:
        make_settings(
            heroos_env=environment,
            database_url=RUNTIME_URL,
            migration_database_url=MIGRATION_URL,
            **COGNITO,
        )

    assert PASSWORD_CANARY not in str(e.value)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_reads_database_url_from_environment(
    environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", RUNTIME_URL)

    settings = make_settings(heroos_env=environment, **COGNITO)

    assert settings.database_url.get_secret_value() == RUNTIME_URL


@pytest.mark.parametrize("value", [None, "", "   "])
def test_development_has_no_database_default(value: str | None) -> None:
    # A built-in default would be a committed credential.
    values = {} if value is None else {"database_url": value}
    with pytest.raises(ValidationError, match="DATABASE_URL must be explicitly configured"):
        make_settings(**values)


def test_database_settings_have_no_defaults() -> None:
    settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url is None
    assert settings.migration_database_url is None
    for require, name in (
        (settings.require_database_url, "DATABASE_URL"),
        (settings.require_migration_database_url, "MIGRATION_DATABASE_URL"),
    ):
        with pytest.raises(DatabaseConfigurationError, match=f"{name} is not set"):
            require()


def test_migration_tooling_needs_no_api_configuration() -> None:
    # Alembic and the backup tooling load DatabaseSettings only.
    settings = DatabaseSettings(_env_file=None, migration_database_url=MIGRATION_URL)  # type: ignore[call-arg]

    assert settings.require_migration_database_url() == MIGRATION_URL


def test_migrations_without_migration_database_url_fail_without_fallback() -> None:
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HEROOS_") and name not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=API_ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "MIGRATION_DATABASE_URL is not set" in result.stderr


def test_startup_with_development_database_fallback_fails_without_echoing_secrets() -> None:
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("HEROOS_") and name not in {"DATABASE_URL", "MIGRATION_DATABASE_URL"}
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=API_ROOT,
        env={
            **clean,
            "HEROOS_ENV": "production",
            "HEROOS_AUTH_PROVIDER": "cognito",
            "HEROOS_COGNITO_ISSUER": COGNITO["heroos_cognito_issuer"],
            "HEROOS_COGNITO_APP_CLIENT_ID": COGNITO["heroos_cognito_app_client_id"],
            "MIGRATION_DATABASE_URL": MIGRATION_URL,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "DATABASE_URL must be explicitly configured" in result.stderr
    assert PASSWORD_CANARY not in result.stderr + result.stdout


# Repository hygiene -----------------------------------------------------------


def _lines(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text().splitlines()}


def test_env_files_are_ignored_by_git_and_docker() -> None:
    for ignore_file in (".gitignore", ".dockerignore"):
        lines = _lines(REPO_ROOT / ignore_file)
        assert {".env", ".env.*", "!.env.example"} <= lines, ignore_file


def test_api_image_copies_only_manifests_application_code_and_public_ca() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text()
    copies = re.findall(r"^COPY\s+(.+)$", dockerfile, flags=re.MULTILINE)
    sources = {
        source
        for line in copies
        if "--from=" not in line
        for source in line.split()[:-1]
        if not source.startswith("--")
    }

    # The CA is a public certificate, pinned in test_database_ca.py.
    assert sources == {
        "apps/api/pyproject.toml",
        "apps/api/uv.lock",
        "apps/api/app",
        "apps/api/certs/supabase-root-2021-ca.crt",
    }


def test_env_example_contains_no_credentials() -> None:
    values = dict(
        line.split("=", 1)
        for line in (REPO_ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    # Generated by `make env-init`; an empty value stops Compose and the API.
    for name in (
        "HEROOS_DB_ADMIN_PASSWORD",
        "HEROOS_DB_APP_PASSWORD",
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "HEROOS_DEV_AUTH_SECRET",
    ):
        assert values[name] == "", name
    assert values["HEROOS_ENV"] == "development"
    assert not [name for name in values if name.startswith("AWS_")]
