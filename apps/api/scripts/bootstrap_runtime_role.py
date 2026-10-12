"""Create or update the LOCAL API runtime database login role.

Usage (from apps/api, or ``make db-runtime-role`` from the repo root):

    uv run python -m scripts.bootstrap_runtime_role

Reads ``MIGRATION_DATABASE_URL`` (admin connection) and ``DATABASE_URL`` (the
runtime login role and its password) and ensures that role:

- can log in with that password,
- is not SUPERUSER, BYPASSRLS, CREATEDB or CREATEROLE,
- is a member of ``heroos_app_runtime``, which holds the table privileges granted
  by migrations.

The password must follow the managed-password policy (64 lowercase hex
characters, ``make env-init``), so the retired committed development defaults
are refused. It is sent only as a client-side SCRAM-SHA-256 verifier, never as
plaintext SQL (``scripts.scram``).

Roles are cluster-wide. Setting the shared ``heroos_app`` password from a
disposable ``*_test`` database is refused: verification suites create their own
disposable login role instead, so they can never reset the live runtime role.

Idempotent; safe on new and existing local databases. Local development and CI
only: it refuses any non-local database host. Deployed environments provision
their runtime login role through deployment configuration. Not shipped in the
API image.

``bootstrap_operator_role`` does the same for a local identity-operator login
(``heroos_op_*``, ADR-008): a member of ``heroos_identity_operator`` only, never
of ``heroos_app_runtime``. The group itself comes from migration B1a.
"""

import os
import re
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from app.core.database_settings import DatabaseConfigurationError, DatabaseSettings
from scripts.scram import PasswordPolicyError, check_password, redact_verifiers, scram_verifier

RUNTIME_GROUP_ROLE = "heroos_app_runtime"
OPERATOR_GROUP_ROLE = "heroos_identity_operator"
# The live API login role. Verification suites never manage it.
SHARED_RUNTIME_LOGIN = "heroos_app"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})
_ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_OPERATOR_LOGIN = re.compile(r"heroos_op_[a-z0-9_]{1,52}")


class BootstrapError(Exception):
    pass


def _libpq(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def bootstrap_runtime_role(admin_url: str, runtime_url: str) -> None:
    admin = make_url(admin_url)
    runtime = make_url(runtime_url)

    for url in (admin, runtime):
        if url.host not in LOCAL_HOSTS:
            raise BootstrapError("refusing to manage roles on a non-local database host")
    login = runtime.username or ""
    password = runtime.password
    if not _ROLE_NAME.fullmatch(login):
        raise BootstrapError("DATABASE_URL must name a lowercase runtime role")
    if login in (admin.username, RUNTIME_GROUP_ROLE, OPERATOR_GROUP_ROLE) or (
        _OPERATOR_LOGIN.fullmatch(login)
    ):
        raise BootstrapError(
            "DATABASE_URL must use the dedicated runtime role (e.g. heroos_app), "
            "not the migration/admin role"
        )
    if not password:
        raise BootstrapError("DATABASE_URL must include the runtime role password")
    if login == SHARED_RUNTIME_LOGIN and (runtime.database or "").endswith("_test"):
        raise BootstrapError(
            f"refusing to manage the shared {SHARED_RUNTIME_LOGIN} role from a disposable test "
            "database; verification suites must use a disposable login role"
        )
    try:
        check_password(password, "the DATABASE_URL password")
    except PasswordPolicyError as exc:
        raise BootstrapError(str(exc)) from None

    _create_or_update_login(admin, login, password, RUNTIME_GROUP_ROLE, create_group=True)


def bootstrap_operator_role(admin_url: str, operator_url: str) -> None:
    """Create or update a LOCAL identity-operator login (``heroos_op_*``)."""
    admin = make_url(admin_url)
    operator = make_url(operator_url)

    for url in (admin, operator):
        if url.host not in LOCAL_HOSTS:
            raise BootstrapError("refusing to manage roles on a non-local database host")
    login = operator.username or ""
    password = operator.password
    if not _OPERATOR_LOGIN.fullmatch(login):
        raise BootstrapError("the operator login must be named heroos_op_<handle>")
    if not password:
        raise BootstrapError("the operator URL must include the operator password")
    try:
        check_password(password, "the operator password")
    except PasswordPolicyError as exc:
        raise BootstrapError(str(exc)) from None

    _create_or_update_login(admin, login, password, OPERATOR_GROUP_ROLE, create_group=False)


def _create_or_update_login(
    admin: URL, login: str, password: str, group: str, *, create_group: bool
) -> None:
    login_role = sql.Identifier(login)
    group_role = sql.Identifier(group)
    attributes = sql.SQL("NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT")

    with psycopg.connect(_libpq(admin), autocommit=True) as conn:
        if create_group:
            # Migrations create the privilege role too; creating it here keeps
            # this script independent of migration order.
            conn.execute(
                sql.SQL(
                    "DO $$ BEGIN"
                    " IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {name}) THEN"
                    " CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;"
                    " END IF; END $$"
                ).format(name=sql.Literal(group), role=group_role)
            )
        elif not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (group,)).fetchone():
            raise BootstrapError(f"{group} does not exist; apply the migrations first")
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
        verb = sql.SQL("ALTER ROLE" if exists else "CREATE ROLE")
        conn.execute(
            sql.SQL("{verb} {role} LOGIN {attributes} PASSWORD {verifier}").format(
                verb=verb,
                role=login_role,
                attributes=attributes,
                verifier=sql.Literal(scram_verifier(password)),
            )
        )
        conn.execute(sql.SQL("GRANT {group} TO {role}").format(group=group_role, role=login_role))

        # Verify from the catalog rather than trusting the statements above.
        privileged = conn.execute(
            """
            SELECT EXISTS (
                SELECT FROM pg_roles r
                WHERE (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole)
                  AND pg_has_role(%(login)s, r.oid, 'MEMBER')
            )
            """,
            {"login": login},
        ).fetchone()
        if privileged is None or privileged[0]:
            raise BootstrapError(f"role {login} can bypass Row-Level Security")
        # Operator and API runtime capabilities never meet in one login.
        other = RUNTIME_GROUP_ROLE if group == OPERATOR_GROUP_ROLE else OPERATOR_GROUP_ROLE
        crossed = conn.execute(
            "SELECT EXISTS (SELECT FROM pg_roles r WHERE r.rolname = %(other)s"
            " AND pg_has_role(%(login)s, r.oid, 'MEMBER'))",
            {"other": other, "login": login},
        ).fetchone()
        if crossed is None or crossed[0]:
            raise BootstrapError(f"role {login} is also a member of {other}")


def main(argv: list[str] | None = None) -> int:
    # `--operator`: local identity-operator login from HEROOS_OPERATOR_DATABASE_URL.
    operator = "--operator" in (sys.argv[1:] if argv is None else argv)
    settings = DatabaseSettings()
    try:
        admin_url = settings.require_migration_database_url()
        if operator:
            login_url = os.environ.get("HEROOS_OPERATOR_DATABASE_URL", "")
            if not login_url:
                raise BootstrapError("HEROOS_OPERATOR_DATABASE_URL is not set")
            bootstrap_operator_role(admin_url, login_url)
        else:
            login_url = settings.require_database_url()
            bootstrap_runtime_role(admin_url, login_url)
    except (BootstrapError, DatabaseConfigurationError, psycopg.Error) as exc:
        # psycopg errors never include the connection password; a failing
        # statement could quote the verifier, which is redacted as well.
        print(f"error: {redact_verifiers(str(exc))}", file=sys.stderr)
        return 1
    kind = "Operator" if operator else "Runtime"
    print(f"{kind} role {make_url(login_url).username} is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
