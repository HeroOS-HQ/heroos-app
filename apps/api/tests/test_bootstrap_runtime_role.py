"""The local runtime-role bootstrap refuses unsafe targets before connecting and
sends the password only as a client-side SCRAM-SHA-256 verifier."""

import secrets
from typing import Any

import psycopg
import pytest
from psycopg import sql

from scripts import bootstrap_runtime_role as bootstrap_module
from scripts.bootstrap_runtime_role import BootstrapError, bootstrap_runtime_role

ADMIN_PASSWORD = secrets.token_hex(32)
RUNTIME_PASSWORD = secrets.token_hex(32)
ADMIN = f"postgresql+psycopg://heroos:{ADMIN_PASSWORD}@localhost:5433/heroos"
RUNTIME = f"postgresql+psycopg://heroos_app:{RUNTIME_PASSWORD}@localhost:5433/heroos"
WEAK_PASSWORD = "heroos_app_password"


@pytest.mark.parametrize(
    ("admin_url", "runtime_url"),
    [
        pytest.param(
            "postgresql+psycopg://heroos:x@prod.example.com/heroos", RUNTIME, id="remote-admin"
        ),
        pytest.param(
            ADMIN, "postgresql+psycopg://heroos_app:x@rds.amazonaws.com/heroos", id="remote-runtime"
        ),
        pytest.param(ADMIN, ADMIN, id="runtime-is-admin"),
        pytest.param(
            ADMIN,
            "postgresql+psycopg://heroos_app_runtime:x@localhost:5433/heroos",
            id="runtime-is-privilege-role",
        ),
        pytest.param(
            ADMIN, "postgresql+psycopg://heroos_app@localhost:5433/heroos", id="no-password"
        ),
        pytest.param(
            ADMIN, 'postgresql+psycopg://"x; DROP":pw@localhost:5433/heroos', id="unsafe-name"
        ),
        # Hand-typed, placeholder or retired committed-default style passwords.
        pytest.param(
            ADMIN,
            f"postgresql+psycopg://heroos_app:{WEAK_PASSWORD}@localhost:5433/heroos",
            id="weak-password",
        ),
        pytest.param(
            ADMIN,
            f"postgresql+psycopg://heroos_app:{RUNTIME_PASSWORD.upper()}@localhost:5433/heroos",
            id="non-policy-password",
        ),
        # Roles are cluster-wide: a test database must never manage heroos_app.
        pytest.param(
            ADMIN,
            f"postgresql+psycopg://heroos_app:{RUNTIME_PASSWORD}"
            "@localhost:5433/x_tenant_isolation_test",
            id="shared-role-from-test-database",
        ),
    ],
)
def test_refuses_unsafe_configuration(
    admin_url: str, runtime_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never_connect(*_: Any, **__: Any) -> None:
        raise AssertionError("refused configuration must not connect")

    monkeypatch.setattr(psycopg, "connect", never_connect)
    with pytest.raises(BootstrapError) as exc_info:
        bootstrap_runtime_role(admin_url, runtime_url)

    assert RUNTIME_PASSWORD not in str(exc_info.value)
    assert RUNTIME_PASSWORD.upper() not in str(exc_info.value)


class _Result:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> _Result:
        rendered = query.as_string() if isinstance(query, sql.Composable) else str(query)
        self.statements.append(rendered)
        if "FROM pg_roles WHERE rolname" in rendered:
            return _Result(None)  # role does not exist yet: CREATE ROLE
        return _Result((False,))  # not privileged


@pytest.mark.parametrize(
    "runtime_url",
    [
        pytest.param(RUNTIME, id="shared-role-on-development-database"),
        pytest.param(
            f"postgresql+psycopg://heroos_app_t_0a1b2c3d:{RUNTIME_PASSWORD}"
            "@localhost:5433/x_tenant_isolation_test",
            id="disposable-role-on-test-database",
        ),
    ],
)
def test_password_is_sent_only_as_scram_verifier(
    runtime_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _RecordingConnection()
    monkeypatch.setattr(psycopg, "connect", lambda *_, **__: connection)

    bootstrap_runtime_role(ADMIN, runtime_url)

    sent = "\n".join(connection.statements)
    assert RUNTIME_PASSWORD not in sent
    assert ADMIN_PASSWORD not in sent
    role_statement = next(s for s in connection.statements if s.startswith("CREATE ROLE"))
    assert "PASSWORD 'SCRAM-SHA-256$4096:" in role_statement
    assert "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE" in role_statement


def test_main_reports_missing_configuration_without_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    settings_class = bootstrap_module.DatabaseSettings
    monkeypatch.setattr(
        bootstrap_module,
        "DatabaseSettings",
        lambda: settings_class(_env_file=None),  # type: ignore[call-arg]
    )

    assert bootstrap_module.main() == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().err
