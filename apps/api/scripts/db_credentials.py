"""Local database credential management for the untracked root ``.env``.

Usage (from apps/api; the Makefile wraps each command)::

    uv run python -m scripts.db_credentials init   [--port 5433]     # make env-init
    uv run python -m scripts.db_credentials check                    # make env-check
    uv run python -m scripts.db_credentials rotate --backup-dir DIR  # make env-rotate
    uv run python -m scripts.db_credentials apply --confirm          # make db-apply-credentials

See docs/operations/database-credentials.md for the procedure and its approval gates.

- The root ``.env`` (mode 0600, ignored by Git and Docker builds) is the only
  place the local database passwords live. Docker Compose reads
  ``HEROOS_DB_ADMIN_PASSWORD`` / ``HEROOS_DB_APP_PASSWORD`` from it; host tooling
  reads ``MIGRATION_DATABASE_URL`` / ``DATABASE_URL``. ``check`` proves they agree.
- Passwords are 64 lowercase hex characters (``scripts.scram`` policy), so the
  retired committed development defaults and placeholders are always refused,
  including when an old ``.env`` backup is put back.
- No command prints a password, a password verifier or a full database URL.
  Output names keys and roles only.
- ``init`` never overwrites. ``rotate`` writes a 0600 backup of the previous file
  first and only changes the managed keys. Neither touches the database.
- ``apply`` is the only command that changes the database: it sets the admin
  and runtime role passwords to the values in ``.env``, as client-side
  SCRAM-SHA-256 verifiers, through the local Docker Compose ``db`` service. It
  changes no other role attribute, membership, ownership or data, verifies that,
  and then logs in with both new passwords. It requires ``--confirm``.
"""

import argparse
import hmac
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.db.runtime_role import UnsafeDatabaseRoleError, check_runtime_role
from scripts.scram import (
    PasswordPolicyError,
    check_password,
    generate_password,
    redact_verifiers,
    scram_verifier,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE: Final = REPO_ROOT / ".env"
EXAMPLE_ENV_FILE: Final = REPO_ROOT / ".env.example"

ADMIN_PASSWORD: Final = "HEROOS_DB_ADMIN_PASSWORD"
APP_PASSWORD: Final = "HEROOS_DB_APP_PASSWORD"
DATABASE_URL: Final = "DATABASE_URL"
MIGRATION_DATABASE_URL: Final = "MIGRATION_DATABASE_URL"
DEV_AUTH_SECRET: Final = "HEROOS_DEV_AUTH_SECRET"
MANAGED_KEYS: Final = (ADMIN_PASSWORD, APP_PASSWORD, MIGRATION_DATABASE_URL, DATABASE_URL)

# Fixed by compose.yaml (POSTGRES_USER / POSTGRES_DB and the api DATABASE_URL).
ADMIN_ROLE: Final = "heroos"
RUNTIME_ROLE: Final = "heroos_app"
DATABASE_NAME: Final = "heroos"
DEFAULT_HOST: Final = "localhost"
DEFAULT_PORT: Final = 5433
LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})

COMPOSE_SERVICE: Final = "db"
PSQL_TIMEOUT_SECONDS: Final = 60
CONNECT_TIMEOUT_SECONDS: Final = 10

# Role properties `apply` must leave exactly as they were.
_ROLE_STATE_SQL: Final = f"""
SELECT r.rolname, r.rolsuper, r.rolinherit, r.rolcreaterole, r.rolcreatedb,
       r.rolcanlogin, r.rolreplication, r.rolbypassrls, r.rolconnlimit,
       coalesce(r.rolvaliduntil::text, '-'),
       coalesce((SELECT string_agg(g.rolname, ',' ORDER BY g.rolname)
                 FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid
                 WHERE m.member = r.oid), '-'),
       a.rolpassword LIKE 'SCRAM-SHA-256$%'
FROM pg_roles r JOIN pg_authid a ON a.oid = r.oid
WHERE r.rolname IN ('{ADMIN_ROLE}', '{RUNTIME_ROLE}')
ORDER BY r.rolname;
"""


class CredentialError(Exception):
    """A credential command was refused or failed. Messages never contain values."""


# .env parsing -----------------------------------------------------------------


def _key_of(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    return key.removeprefix("export ").strip()


def parse_env(content: str) -> tuple[dict[str, str], set[str]]:
    """Return (values, keys defined more than once). Last definition wins."""
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    for line in content.splitlines():
        key = _key_of(line)
        if key is None:
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key in values:
            duplicates.add(key)
        values[key] = value
    return values, duplicates


def render_env(content: str, updates: dict[str, str]) -> str:
    """Replace the value of each key in ``updates``; append missing keys."""
    lines: list[str] = []
    written: set[str] = set()
    for line in content.splitlines():
        key = _key_of(line)
        if key in updates:
            if key in written:
                continue  # drop duplicate definitions of a managed key
            lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            lines.append(line)
    missing = [key for key in updates if key not in written]
    if missing:
        lines += ["", "# Managed by `make env-init` / `make env-rotate`. Never commit."]
        lines += [f"{key}={updates[key]}" for key in missing]
    return "\n".join(lines) + "\n"


def database_url(role: str, password: str, host: str, port: int, database: str) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=role,
        password=password,
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


def generated_values(host: str, port: int, database: str) -> dict[str, str]:
    admin, app = generate_password(), generate_password()
    return {
        ADMIN_PASSWORD: admin,
        APP_PASSWORD: app,
        MIGRATION_DATABASE_URL: database_url(ADMIN_ROLE, admin, host, port, database),
        DATABASE_URL: database_url(RUNTIME_ROLE, app, host, port, database),
    }


# Private file handling ----------------------------------------------------------


def _write_new_private_file(path: Path, content: str) -> None:
    """Create ``path`` (mode 0600). Never follows or replaces an existing file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_private_file(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    _write_new_private_file(temporary, content)
    try:
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _read_env_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CredentialError(f"{path} is missing or not a regular file; run `make env-init`")
    return path.read_text(encoding="utf-8")


def _is_within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _check_private_directory(directory: Path) -> Path:
    if directory.is_symlink() or not directory.is_dir():
        raise CredentialError(f"backup directory {directory} must be an existing directory")
    if _is_within(directory, REPO_ROOT):
        raise CredentialError("backup directory must be outside the repository")
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise CredentialError(
            f"backup directory {directory} must be owned by you with mode 0700 "
            "(install -d -m 700 DIR)"
        )
    return directory


# check ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    name: str
    ok: bool | None  # None: skipped
    detail: str = ""


def _git(directory: Path, *arguments: str) -> int:
    try:
        return subprocess.run(
            ["git", "-C", str(directory), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def _git_findings(path: Path) -> list[Finding]:
    directory = path.resolve().parent
    if _git(directory, "rev-parse", "--is-inside-work-tree") != 0:
        return [Finding("git", None, "not inside a Git work tree")]
    return [
        Finding("git-ignored", _git(directory, "check-ignore", "-q", path.name) == 0),
        Finding(
            "git-untracked",
            _git(directory, "ls-files", "--error-unmatch", "--", path.name) != 0,
            "the file is tracked by Git: remove it from the index and treat every "
            "value in it as exposed",
        ),
    ]


def _url_findings(
    values: dict[str, str], key: str, role: str, password: str | None
) -> tuple[list[Finding], URL | None]:
    raw = values.get(key, "")
    if not raw:
        return [Finding(key, False, "missing or empty")], None
    try:
        url = make_url(raw)
    except ArgumentError:
        return [Finding(key, False, "not a valid database URL")], None
    problems = []
    if url.username != role:
        problems.append(f"role must be {role}")
    if url.host not in LOCAL_HOSTS:
        problems.append("host must be the local Docker Compose database (localhost)")
    if url.database != DATABASE_NAME:
        problems.append(f"database must be {DATABASE_NAME}")
    if password is None or not hmac.compare_digest(
        (url.password or "").encode(), password.encode()
    ):
        problems.append(
            f"password does not match {ADMIN_PASSWORD if role == ADMIN_ROLE else APP_PASSWORD}"
        )
    return [Finding(key, not problems, "; ".join(problems))], url


def check_env_file(path: Path) -> list[Finding]:
    """Validate the .env file without ever returning a value."""
    if path.is_symlink() or not path.is_file():
        return [Finding("file", False, f"{path} is missing or not a regular file")]
    info = path.stat()
    findings = [
        Finding(
            "file-permissions",
            info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
            "must be owned by you with mode 0600 (chmod 600 .env)",
        ),
        *_git_findings(path),
    ]
    values, duplicates = parse_env(path.read_text(encoding="utf-8"))
    for key in sorted(duplicates & {*MANAGED_KEYS, DEV_AUTH_SECRET}):
        findings.append(Finding(key, False, "defined more than once"))

    passwords: dict[str, str | None] = {}
    for key in (ADMIN_PASSWORD, APP_PASSWORD):
        try:
            passwords[key] = check_password(values.get(key), key)
            findings.append(Finding(key, True))
        except PasswordPolicyError as exc:
            passwords[key] = None
            findings.append(Finding(key, False, str(exc)))
    admin, app = passwords[ADMIN_PASSWORD], passwords[APP_PASSWORD]
    if admin and app and hmac.compare_digest(admin, app):
        findings.append(
            Finding("distinct-passwords", False, "admin and runtime passwords must differ")
        )

    admin_findings, admin_url = _url_findings(values, MIGRATION_DATABASE_URL, ADMIN_ROLE, admin)
    runtime_findings, runtime_url = _url_findings(values, DATABASE_URL, RUNTIME_ROLE, app)
    findings += admin_findings + runtime_findings
    if admin_url is not None and runtime_url is not None:
        same_target = (admin_url.host, admin_url.port) == (runtime_url.host, runtime_url.port)
        findings.append(
            Finding("same-database", same_target, "both URLs must name the same host and port")
        )

    secret = values.get(DEV_AUTH_SECRET, "")
    if not secret:
        findings.append(Finding(DEV_AUTH_SECRET, None, "not set"))
    else:
        try:
            check_password(secret, DEV_AUTH_SECRET)
            reused = any(p and hmac.compare_digest(secret, p) for p in (admin, app))
            findings.append(
                Finding(DEV_AUTH_SECRET, not reused, "must not reuse a database password")
            )
        except PasswordPolicyError as exc:
            findings.append(Finding(DEV_AUTH_SECRET, False, str(exc)))
    return findings


def _report(findings: Sequence[Finding]) -> bool:
    for finding in findings:
        if finding.ok is None:
            print(f"SKIP  {finding.name}: {finding.detail}")
        elif finding.ok:
            print(f"OK    {finding.name}")
        else:
            print(f"FAIL  {finding.name}: {finding.detail}")
    return all(finding.ok is not False for finding in findings)


# Commands --------------------------------------------------------------------------


def command_init(path: Path, example: Path, port: int) -> None:
    if path.exists() or path.is_symlink():
        raise CredentialError(
            f"{path} already exists and is never overwritten; check it with `make env-check` "
            "or rotate it with `make env-rotate`"
        )
    template = example.read_text(encoding="utf-8") if example.is_file() else ""
    updates = generated_values(DEFAULT_HOST, port, DATABASE_NAME)
    updates[DEV_AUTH_SECRET] = generate_password()
    _write_new_private_file(path, render_env(template, updates))
    print(f"Created {path} (0600) with generated values for: {', '.join(updates)}.")
    print("Values are not displayed. Never commit or share this file.")


def command_rotate(path: Path, backup_dir: Path, dev_auth_secret: bool) -> None:
    content = _read_env_file(path)
    _check_private_directory(backup_dir)
    values, _ = parse_env(content)

    host, port, database = DEFAULT_HOST, DEFAULT_PORT, DATABASE_NAME
    try:
        current = make_url(values.get(MIGRATION_DATABASE_URL, ""))
        if current.host in LOCAL_HOSTS and current.port:
            host, port = current.host, current.port
    except ArgumentError:
        pass  # rebuilt with the local defaults
    updates = generated_values(host, port, database)
    if dev_auth_secret:
        updates[DEV_AUTH_SECRET] = generate_password()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"env.pre-rotation.{stamp}"
    _write_new_private_file(backup, content)
    _replace_private_file(path, render_env(content, updates))
    print(f"Previous {path.name} saved to {backup} (0600).")
    print(f"Generated new values for: {', '.join(updates)}. Values are not displayed.")
    print(
        "The database still accepts only the previous passwords. Next (approval gate): "
        "`make db-apply-credentials CONFIRM=yes`, then recreate the api container."
    )


Runner = Callable[[str], str]


def compose_psql(sql: str) -> str:
    """Run SQL as the admin role inside the Compose db service (stdin, never argv)."""
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                COMPOSE_SERVICE,
                "psql",
                "-X",
                "-q",
                "-t",
                "-A",
                "-F",
                "|",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                "VERBOSITY=terse",
                "-U",
                ADMIN_ROLE,
                "-d",
                "postgres",
            ],  # fmt: skip
            input=sql,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=PSQL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CredentialError(
            f"could not run psql in the Compose db service: {type(exc).__name__}"
        ) from None
    if result.returncode != 0:
        raise CredentialError(f"psql failed: {redact_verifiers(result.stderr).strip()}")
    return result.stdout


def _role_state(run: Runner) -> list[list[str]]:
    rows = [line.split("|") for line in run(_ROLE_STATE_SQL).splitlines() if line.strip()]
    found = {row[0] for row in rows}
    missing = {ADMIN_ROLE, RUNTIME_ROLE} - found
    if missing:
        raise CredentialError(
            f"role(s) {', '.join(sorted(missing))} do not exist; `apply` only changes the "
            "passwords of existing roles"
        )
    return rows


def _verify_login(url: str, runtime: bool) -> None:
    engine = create_engine(
        url, poolclass=NullPool, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    )
    try:
        with engine.connect() as connection:
            if runtime:
                check_runtime_role(connection)
            else:
                connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Report the driver error class only: messages can include connection details.
        role = RUNTIME_ROLE if runtime else ADMIN_ROLE
        cause = getattr(exc, "orig", None) or exc
        raise CredentialError(f"login as {role} failed ({type(cause).__name__})") from None
    except UnsafeDatabaseRoleError as exc:
        raise CredentialError(str(exc)) from None
    finally:
        engine.dispose()


def command_apply(path: Path, confirm: bool, run: Runner = compose_psql) -> None:
    if not confirm:
        raise CredentialError(
            "apply changes database role passwords; re-run with --confirm "
            "(make db-apply-credentials CONFIRM=yes) after approval"
        )
    if path.resolve() != DEFAULT_ENV_FILE.resolve():
        raise CredentialError(
            "apply uses the repository .env only: it is the file Docker Compose reads"
        )
    if not _report(check_env_file(path)):
        raise CredentialError("the .env check failed; nothing was changed")
    values, _ = parse_env(_read_env_file(path))

    before = _role_state(run)
    statements = "".join(
        f"ALTER ROLE {role} PASSWORD '{scram_verifier(values[key])}';\n"
        for role, key in ((ADMIN_ROLE, ADMIN_PASSWORD), (RUNTIME_ROLE, APP_PASSWORD))
    )
    run(f"BEGIN;\n{statements}COMMIT;\n")
    after = _role_state(run)

    if [row[:-1] for row in before] != [row[:-1] for row in after]:
        raise CredentialError("role attributes or memberships changed unexpectedly; investigate")
    if not all(row[-1] == "t" for row in after):
        raise CredentialError("a role password is not stored as SCRAM-SHA-256")

    _verify_login(values[MIGRATION_DATABASE_URL], runtime=False)
    _verify_login(values[DATABASE_URL], runtime=True)
    print(
        f"Applied the .env passwords to roles {ADMIN_ROLE} and {RUNTIME_ROLE}: attributes and "
        "memberships unchanged, both logins verified, runtime role still RLS-restricted."
    )
    print("Next: docker compose up -d --no-deps --force-recreate api")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.db_credentials", description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="create .env with generated credentials")
    init_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    commands.add_parser("check", help="validate .env without printing values")
    rotate_parser = commands.add_parser("rotate", help="back up .env and generate new values")
    rotate_parser.add_argument("--backup-dir", type=Path, required=True)
    rotate_parser.add_argument(
        "--dev-auth-secret", action="store_true", help=f"also rotate {DEV_AUTH_SECRET}"
    )
    apply_parser = commands.add_parser("apply", help="set role passwords to the .env values")
    apply_parser.add_argument("--confirm", action="store_true")
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "init":
            command_init(arguments.env_file, EXAMPLE_ENV_FILE, arguments.port)
        elif arguments.command == "check":
            if not _report(check_env_file(arguments.env_file)):
                return 1
        elif arguments.command == "rotate":
            command_rotate(arguments.env_file, arguments.backup_dir, arguments.dev_auth_secret)
        else:
            command_apply(arguments.env_file, arguments.confirm)
    except (CredentialError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
