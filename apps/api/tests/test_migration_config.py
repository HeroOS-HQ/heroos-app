"""Alembic needs database configuration only, never API environment/auth settings."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

# Offline (--sql) mode renders the full migration chain without a database.
RUN_ALEMBIC_OFFLINE = """
import sys
from alembic.config import main
main(argv=["upgrade", "head", "--sql"])
assert "app.core.config" not in sys.modules, "migrations imported API settings"
"""


def _run_alembic(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean_env = {
        name: value for name, value in os.environ.items() if not name.startswith("HEROOS_")
    }
    return subprocess.run(
        [sys.executable, "-c", RUN_ALEMBIC_OFFLINE],
        cwd=API_ROOT,
        env={**clean_env, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="no-heroos-env"),
        pytest.param(
            {"HEROOS_ENV": "production", "HEROOS_AUTH_PROVIDER": "development"},
            id="invalid-api-auth-config",
        ),
    ],
)
def test_migrations_run_without_api_auth_configuration(env: dict[str, str]) -> None:
    result = _run_alembic(
        {**env, "MIGRATION_DATABASE_URL": "postgresql+psycopg://heroos:unused@db.invalid/heroos"}
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE companies" in result.stdout
    assert "CREATE TABLE memberships" in result.stdout
    assert "ALTER TABLE memberships ENABLE ROW LEVEL SECURITY" in result.stdout


def test_migrations_connect_with_migration_role_not_runtime_role() -> None:
    # Online mode against unresolvable hosts: the connection error names the
    # host Alembic actually used.
    clean_env = {
        name: value for name, value in os.environ.items() if not name.startswith("HEROOS_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=API_ROOT,
        env={
            **clean_env,
            "DATABASE_URL": "postgresql+psycopg://runtime:unused@runtime.invalid/heroos",
            "MIGRATION_DATABASE_URL": "postgresql+psycopg://admin:unused@admin.invalid/heroos",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "admin.invalid" in result.stderr
    assert "runtime.invalid" not in result.stderr


def test_api_settings_still_enforce_auth_rules_in_same_environment() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=API_ROOT,
        env={
            **{n: v for n, v in os.environ.items() if not n.startswith("HEROOS_")},
            "HEROOS_ENV": "production",
            "HEROOS_AUTH_PROVIDER": "development",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode != 0
    assert "HEROOS_AUTH_PROVIDER must be 'cognito'" in result.stderr
