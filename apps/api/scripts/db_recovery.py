"""Logical PostgreSQL backup and restore for HeroOS (``pg_dump`` / ``pg_restore``).

Usage (from apps/api; ``make backup-restore-check`` exercises both end to end)::

    uv run python -m scripts.db_recovery backup \\
        --database heroos --output /private/dir/heroos.dump [--pg-tools compose]
    uv run python -m scripts.db_recovery restore \\
        --database heroos_restored --input /private/dir/heroos.dump [--pg-tools compose]

See docs/architecture/backup-and-recovery.md for the full procedure.

- Runs as the migration/admin role from ``MIGRATION_DATABASE_URL``. The API
  runtime role is refused: it is subject to Row-Level Security and would dump
  an empty or partial database.
- Credentials reach ``pg_dump`` / ``pg_restore`` only through ``PG*``
  environment variables of the child process. The password is never a command
  argument and is never printed; tool error output is redacted.
- Archives are custom-format, created with ``O_EXCL`` and mode 0600 inside an
  existing private (0700-style) directory outside the repository. A failed
  backup removes its partial archive.
- Restore only targets an existing, *empty* database that is not a protected or
  configured database and has no production-like name, and only after the
  cluster-wide roles it references exist. It runs in a single transaction and
  stops at the first error.
- A database dump is not a complete disaster-recovery backup: cluster roles and
  settings are not included.

``--pg-tools``:

- ``local``: ``pg_dump`` / ``pg_restore`` on ``PATH`` (client major version
  must be >= the server's), connecting to the host/port of the admin URL.
- ``compose``: the PostgreSQL 16 client inside the local Docker Compose ``db``
  service, connecting over the Compose network to ``db:5432`` so password
  authentication is exercised. Local development and CI only.
"""

import argparse
import os
import re
import stat
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import psycopg
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.database_settings import DatabaseSettings
from scripts.bootstrap_runtime_role import RUNTIME_GROUP_ROLE

PgToolsMode = Literal["local", "compose"]

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
ARCHIVE_MAGIC: Final = b"PGDMP"
PRIVATE_FILE_MODE: Final = 0o600
TOOL_TIMEOUT_SECONDS: Final = 600
CONNECT_TIMEOUT_SECONDS: Final = "10"

# Never restore into these, whatever the configuration says.
PROTECTED_DATABASES: Final = frozenset(
    {"postgres", "template0", "template1", "heroos", "rdsadmin", "azure_maintenance"}
)
_PRODUCTION_LIKE: Final = re.compile(r"(^|_)(prod|production|live|primary)(_|$)")
_DATABASE_NAME: Final = re.compile(r"[a-z][a-z0-9_]{0,62}")

COMPOSE_SERVICE: Final = "db"
COMPOSE_HOST: Final = "db"
COMPOSE_PORT: Final = "5432"
PG_ENVIRONMENT: Final = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")
_POSIX: Final = os.name == "posix"


class RecoveryError(Exception):
    """A backup or restore was refused or failed. Messages never contain secrets."""


def validate_database_name(name: str) -> str:
    if not isinstance(name, str) or not _DATABASE_NAME.fullmatch(name):
        raise RecoveryError("database name must be a lowercase PostgreSQL identifier")
    return name


def validate_restore_target(name: str, configured: frozenset[str] = frozenset()) -> str:
    """Refuse every restore target that could be a live or system database."""
    validate_database_name(name)
    if name in PROTECTED_DATABASES or name in configured:
        raise RecoveryError(f"refusing to restore into protected database {name!r}")
    if _PRODUCTION_LIKE.search(name):
        raise RecoveryError(f"refusing to restore into production-like database {name!r}")
    return name


@dataclass(frozen=True)
class AdminConnection:
    """The migration/admin role, kept out of argv and repr."""

    host: str
    port: int
    user: str
    password: SecretStr | None

    @classmethod
    def from_urls(cls, admin_url: str, runtime_url: str | None = None) -> "AdminConnection":
        admin = make_url(admin_url)
        user = admin.username or ""
        if not user or not admin.host:
            raise RecoveryError("MIGRATION_DATABASE_URL must name a host and the admin role")
        runtime_user = make_url(runtime_url).username if runtime_url else None
        if user in {RUNTIME_GROUP_ROLE, runtime_user}:
            raise RecoveryError(
                "backup and restore must use the migration/admin role, not the API runtime role"
            )
        return cls(
            host=admin.host,
            port=admin.port or 5432,
            user=user,
            password=SecretStr(admin.password) if admin.password else None,
        )

    def libpq_environment(self, database: str) -> dict[str, str]:
        environment = {
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGUSER": self.user,
            "PGDATABASE": database,
            "PGCONNECT_TIMEOUT": CONNECT_TIMEOUT_SECONDS,
        }
        if self.password is not None:
            environment["PGPASSWORD"] = self.password.get_secret_value()
        return environment

    def connect(self, database: str) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password.get_secret_value() if self.password else None,
            dbname=database,
            connect_timeout=int(CONNECT_TIMEOUT_SECONDS),
            autocommit=True,
        )

    def redact(self, text: str) -> str:
        if self.password is not None and self.password.get_secret_value():
            text = text.replace(self.password.get_secret_value(), "***")
        return text


@dataclass(frozen=True)
class PgTools:
    mode: PgToolsMode = "local"

    def command(self, tool: str, arguments: Sequence[str]) -> list[str]:
        if self.mode == "compose":
            # `-e NAME` without a value: Docker copies it from this process's
            # environment, so the password is never on a command line.
            passthrough = [flag for name in PG_ENVIRONMENT for flag in ("-e", name)]
            return [
                "docker",
                "compose",
                "exec",
                "-T",
                *passthrough,
                COMPOSE_SERVICE,
                tool,
                *arguments,
            ]
        return [tool, *arguments]

    def environment(self, connection: AdminConnection, database: str) -> dict[str, str]:
        libpq = connection.libpq_environment(database)
        if self.mode == "compose":
            libpq.update({"PGHOST": COMPOSE_HOST, "PGPORT": COMPOSE_PORT})
        return {**os.environ, **libpq}

    def run(
        self,
        connection: AdminConnection,
        database: str,
        tool: str,
        arguments: Sequence[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
    ) -> None:
        try:
            result = subprocess.run(
                self.command(tool, arguments),
                stdin=stdin if stdin is not None else subprocess.DEVNULL,
                stdout=stdout if stdout is not None else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=self.environment(connection, database),
                cwd=REPO_ROOT if self.mode == "compose" else None,
                timeout=TOOL_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecoveryError(f"{tool} could not run ({type(exc).__name__})") from None
        if result.returncode != 0:
            detail = connection.redact(result.stderr.decode(errors="replace")).strip()
            tail = "\n".join(detail.splitlines()[-20:])
            raise RecoveryError(f"{tool} failed (exit {result.returncode}):\n{tail}")


def _require_private_directory(directory: Path) -> None:
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise RecoveryError("backup directory must be an existing directory (not a symlink)")
    if _POSIX and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise RecoveryError("backup directory must be private (e.g. 0700) and owned by you")


def _require_outside_repository(path: Path) -> None:
    if path.resolve().is_relative_to(REPO_ROOT):
        raise RecoveryError("backup archives must never be written inside the repository")


def _check_archive(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise RecoveryError("backup archive not found") from None
    if not stat.S_ISREG(info.st_mode):
        raise RecoveryError("backup archive must be a regular file (not a symlink)")
    if _POSIX and stat.S_IMODE(info.st_mode) & 0o077:
        raise RecoveryError("backup archive permissions are too broad (expected 0600)")
    with path.open("rb") as handle:
        if handle.read(len(ARCHIVE_MAGIC)) != ARCHIVE_MAGIC:
            raise RecoveryError("not a PostgreSQL custom-format archive")


def backup(connection: AdminConnection, tools: PgTools, database: str, output: Path) -> Path:
    """Write a custom-format logical backup of ``database`` to ``output`` (0600)."""
    validate_database_name(database)
    output = output.absolute()
    _require_outside_repository(output)
    _require_private_directory(output.parent)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(output, flags, PRIVATE_FILE_MODE)
    except FileExistsError:
        raise RecoveryError("backup archive already exists; refusing to overwrite") from None
    try:
        try:
            if _POSIX:
                os.fchmod(fd, PRIVATE_FILE_MODE)
            tools.run(
                connection,
                database,
                "pg_dump",
                ["--format=custom", "--no-password", f"--dbname={database}"],
                stdout=fd,
            )
        finally:
            os.close(fd)
        _check_archive(output)
    except BaseException:
        # Never leave a partial archive behind.
        with suppress(FileNotFoundError):
            output.unlink()
        raise
    return output


def restore(
    connection: AdminConnection,
    tools: PgTools,
    database: str,
    archive: Path,
    *,
    configured: frozenset[str] = frozenset(),
) -> None:
    """Restore ``archive`` into the existing, empty database ``database``."""
    validate_restore_target(database, configured)
    _check_archive(archive)

    try:
        with connection.connect("postgres") as admin:
            exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if exists.fetchone() is None:
                raise RecoveryError(
                    f"restore target {database!r} does not exist; create it (owned by the "
                    "migration/admin role) before restoring"
                )
            role = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_GROUP_ROLE,))
            if role.fetchone() is None:
                raise RecoveryError(
                    f"cluster role {RUNTIME_GROUP_ROLE!r} is missing; bootstrap roles before "
                    "restoring (docs/architecture/backup-and-recovery.md)"
                )
        with connection.connect(database) as target:
            row = target.execute(
                """
                SELECT count(*) FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'
                """
            ).fetchone()
            if row is None or row[0] != 0:
                raise RecoveryError(f"restore target {database!r} is not empty; refusing")
    except psycopg.Error as exc:
        raise RecoveryError(f"could not inspect restore target ({type(exc).__name__})") from None

    fd = os.open(archive, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        tools.run(
            connection,
            database,
            "pg_restore",
            [
                "--no-password",
                "--exit-on-error",
                "--single-transaction",
                # Objects are owned by the restoring migration/admin role; the
                # runtime role must never own tables (M1-06 startup guard).
                "--no-owner",
                f"--dbname={database}",
            ],
            stdin=fd,
        )
    finally:
        os.close(fd)


def _configured_databases(settings: DatabaseSettings) -> frozenset[str]:
    names = {
        make_url(url.get_secret_value()).database
        for url in (settings.database_url, settings.migration_database_url)
    }
    return frozenset(name for name in names if name)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.db_recovery", description=__doc__)
    parser.add_argument("--pg-tools", choices=["local", "compose"], default="local")
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", help="pg_dump a database to a private archive")
    backup_parser.add_argument("--database", required=True)
    backup_parser.add_argument("--output", required=True, type=Path)
    restore_parser = commands.add_parser("restore", help="pg_restore into an empty database")
    restore_parser.add_argument("--database", required=True)
    restore_parser.add_argument("--input", required=True, type=Path)
    arguments = parser.parse_args(argv)

    settings = DatabaseSettings()
    tools = PgTools(mode=arguments.pg_tools)
    try:
        connection = AdminConnection.from_urls(
            settings.migration_database_url.get_secret_value(),
            settings.database_url.get_secret_value(),
        )
        if arguments.command == "backup":
            path = backup(connection, tools, arguments.database, arguments.output)
            print(f"Backup of {arguments.database} written ({path.stat().st_size} bytes, 0600).")
        else:
            restore(
                connection,
                tools,
                arguments.database,
                arguments.input,
                configured=_configured_databases(settings),
            )
            print(f"Restored archive into {arguments.database}.")
    except RecoveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
