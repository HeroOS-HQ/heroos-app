"""Backup/restore tooling safety, without a database.

Fake ``pg_dump`` / ``pg_restore`` executables on PATH record their argv and
environment, so these tests prove how credentials are passed, how archives are
protected and what is refused. ``make backup-restore-check`` proves the real
PostgreSQL round trip.
"""

import os
import stat
from pathlib import Path

import pytest

from scripts.db_recovery import (
    REPO_ROOT,
    AdminConnection,
    PgTools,
    RecoveryError,
    backup,
    restore,
    validate_restore_target,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")

PASSWORD = "SUPER_SECRET_PASSWORD_CANARY"
ADMIN_URL = f"postgresql+psycopg://heroos:{PASSWORD}@db.test.invalid:5433/heroos"
RUNTIME_URL = "postgresql+psycopg://heroos_app:runtime@db.test.invalid:5433/heroos"


@pytest.fixture
def connection() -> AdminConnection:
    return AdminConnection.from_urls(ADMIN_URL, RUNTIME_URL)


@pytest.fixture
def private_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "backup"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


@pytest.fixture
def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake pg tools: record argv/env; FAKE_PG_FAIL=1 makes them fail mid-write."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record"
    script = f"""#!/bin/sh
printf '%s\\n' "$0" "$@" >> {record}/argv
env | grep '^PG' | sort >> {record}/env
if [ "$(basename "$0")" = pg_dump ]; then printf 'PGDMP-fake-archive'; fi
if [ "$(basename "$0")" = pg_restore ]; then cat > {record}/restored; fi
if [ -n "$FAKE_PG_FAIL" ]; then
  echo "fatal: connection failed for password $PGPASSWORD" >&2
  exit 1
fi
"""
    record.mkdir()
    for tool in ("pg_dump", "pg_restore"):
        path = bin_dir / tool
        path.write_text(script)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return record


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


# Credentials ----------------------------------------------------------------------


def test_runtime_role_is_refused() -> None:
    with pytest.raises(RecoveryError, match="migration/admin role"):
        AdminConnection.from_urls(RUNTIME_URL, RUNTIME_URL)
    with pytest.raises(RecoveryError, match="migration/admin role"):
        AdminConnection.from_urls(
            "postgresql+psycopg://heroos_app_runtime:x@db.test.invalid/heroos"
        )


def test_password_never_in_argv_or_repr(connection: AdminConnection) -> None:
    for mode_name in ("local", "compose"):
        tools = PgTools(mode=mode_name)  # type: ignore[arg-type]
        command = tools.command("pg_dump", ["--format=custom", "--dbname=heroos"])
        environment = tools.environment(connection, "heroos")
        assert PASSWORD not in " ".join(command)
        assert environment["PGPASSWORD"] == PASSWORD
        assert environment["PGUSER"] == "heroos"
    assert PASSWORD not in repr(connection)


def test_compose_mode_passes_variables_by_name_and_uses_network_auth(
    connection: AdminConnection,
) -> None:
    tools = PgTools(mode="compose")
    command = tools.command("pg_restore", ["--dbname=x"])

    assert command[:4] == ["docker", "compose", "exec", "-T"]
    assert "-e" in command and "PGPASSWORD" in command
    assert not [part for part in command if part.startswith("PGPASSWORD=")]
    environment = tools.environment(connection, "x")
    # Over the Compose network (scram-sha-256), not the trusted loopback socket.
    assert (environment["PGHOST"], environment["PGPORT"]) == ("db", "5432")


# Backup -----------------------------------------------------------------------------


@posix_only
def test_backup_creates_private_archive_without_password_in_argv(
    connection: AdminConnection, private_dir: Path, fake_tools: Path
) -> None:
    previous = os.umask(0)  # prove the mode is explicit, not inherited
    try:
        archive = backup(connection, PgTools(), "heroos_source", private_dir / "a.dump")
    finally:
        os.umask(previous)

    assert archive.read_bytes() == b"PGDMP-fake-archive"
    assert mode(archive) == 0o600
    argv = (fake_tools / "argv").read_text()
    assert PASSWORD not in argv
    assert "--format=custom" in argv and "--dbname=heroos_source" in argv
    assert f"PGPASSWORD={PASSWORD}" in (fake_tools / "env").read_text()


def test_failed_backup_removes_partial_archive_and_redacts_password(
    connection: AdminConnection,
    private_dir: Path,
    fake_tools: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_PG_FAIL", "1")

    with pytest.raises(RecoveryError, match="pg_dump failed") as exc_info:
        backup(connection, PgTools(), "heroos_source", private_dir / "a.dump")

    assert list(private_dir.iterdir()) == []
    assert PASSWORD not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_backup_refuses_to_overwrite(
    connection: AdminConnection, private_dir: Path, fake_tools: Path
) -> None:
    existing = private_dir / "a.dump"
    existing.write_bytes(b"previous")

    with pytest.raises(RecoveryError, match="already exists"):
        backup(connection, PgTools(), "heroos_source", existing)
    assert existing.read_bytes() == b"previous"


@posix_only
@pytest.mark.parametrize("directory_mode", [0o755, 0o750, 0o707, 0o777])
def test_backup_refuses_non_private_directory(
    connection: AdminConnection, tmp_path: Path, fake_tools: Path, directory_mode: int
) -> None:
    directory = tmp_path / "shared"
    directory.mkdir()
    directory.chmod(directory_mode)

    with pytest.raises(RecoveryError, match="private"):
        backup(connection, PgTools(), "heroos_source", directory / "a.dump")
    assert list(directory.iterdir()) == []


def test_backup_refuses_repository_paths(connection: AdminConnection, fake_tools: Path) -> None:
    target = REPO_ROOT / "heroos.dump"

    with pytest.raises(RecoveryError, match="inside the repository"):
        backup(connection, PgTools(), "heroos_source", target)
    assert not target.exists()


@posix_only
def test_backup_refuses_symlinked_directory(
    connection: AdminConnection, private_dir: Path, tmp_path: Path, fake_tools: Path
) -> None:
    link = tmp_path / "link"
    link.symlink_to(private_dir, target_is_directory=True)

    with pytest.raises(RecoveryError, match="not a symlink"):
        backup(connection, PgTools(), "heroos_source", link / "a.dump")


@pytest.mark.parametrize("name", ["", "Heroos", "heroos;drop", "1heroos", "a" * 64, "../x"])
def test_backup_refuses_invalid_database_names(
    connection: AdminConnection, private_dir: Path, name: str
) -> None:
    with pytest.raises(RecoveryError):
        backup(connection, PgTools(), name, private_dir / "a.dump")


# Restore ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "heroos",
        "postgres",
        "template0",
        "template1",
        "rdsadmin",
        "heroos_prod",
        "prod",
        "heroos_production_copy",
        "live_heroos",
        "heroos_primary",
    ],
)
def test_restore_refuses_protected_and_production_like_targets(name: str) -> None:
    with pytest.raises(RecoveryError, match="refusing"):
        validate_restore_target(name)


def test_restore_refuses_configured_databases() -> None:
    with pytest.raises(RecoveryError, match="protected"):
        validate_restore_target("heroos_dev", frozenset({"heroos_dev"}))


@pytest.mark.parametrize(
    "name", ["heroos_backup_restore_test", "heroos_restored_20261008", "heroos_recovery_drill"]
)
def test_restore_accepts_disposable_targets(name: str) -> None:
    assert validate_restore_target(name) == name


@posix_only
def test_restore_refuses_archive_with_broad_permissions(
    connection: AdminConnection, private_dir: Path
) -> None:
    archive = private_dir / "a.dump"
    archive.write_bytes(b"PGDMP-archive")
    archive.chmod(0o644)

    with pytest.raises(RecoveryError, match="too broad"):
        restore(connection, PgTools(), "heroos_backup_restore_test", archive)


def test_restore_refuses_non_archive(connection: AdminConnection, private_dir: Path) -> None:
    archive = private_dir / "a.sql"
    archive.write_bytes(b"DROP DATABASE heroos;")
    archive.chmod(0o600)

    with pytest.raises(RecoveryError, match="custom-format"):
        restore(connection, PgTools(), "heroos_backup_restore_test", archive)


def test_restore_refuses_missing_archive(connection: AdminConnection, private_dir: Path) -> None:
    with pytest.raises(RecoveryError, match="not found"):
        restore(connection, PgTools(), "heroos_backup_restore_test", private_dir / "none")


def test_restore_refuses_protected_target_before_touching_archive_or_database(
    connection: AdminConnection, private_dir: Path, fake_tools: Path
) -> None:
    with pytest.raises(RecoveryError, match="protected"):
        restore(connection, PgTools(), "heroos", private_dir / "never-read.dump")
    assert not (fake_tools / "argv").exists()
