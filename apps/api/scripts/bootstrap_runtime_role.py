"""Create or update the LOCAL API runtime database login role.

Usage (from apps/api, or ``make db-runtime-role`` from the repo root):

    uv run python -m scripts.bootstrap_runtime_role

Reads ``MIGRATION_DATABASE_URL`` (admin connection) and ``DATABASE_URL`` (the
runtime login role and its password) and ensures that role:

- can log in with that password,
- is not SUPERUSER, BYPASSRLS, CREATEDB or CREATEROLE,
- is a member of ``heroos_app_runtime``, which holds the table privileges granted
  by migrations.

Idempotent; safe on new and existing local databases. Local development and CI
only: it refuses any non-local database host. Deployed environments provision
their runtime login role through deployment configuration. Not shipped in the
API image.
"""

import re
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from app.core.database_settings import DatabaseSettings

RUNTIME_GROUP_ROLE = "heroos_app_runtime"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})
_ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


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
    if login in (admin.username, RUNTIME_GROUP_ROLE):
        raise BootstrapError(
            "DATABASE_URL must use the dedicated runtime role (e.g. heroos_app), "
            "not the migration/admin role"
        )
    if not password:
        raise BootstrapError("DATABASE_URL must include the runtime role password")

    login_role = sql.Identifier(login)
    group_role = sql.Identifier(RUNTIME_GROUP_ROLE)
    attributes = sql.SQL("NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT")

    with psycopg.connect(_libpq(admin), autocommit=True) as conn:
        # Migrations create the privilege role too; creating it here keeps this
        # script independent of migration order.
        conn.execute(
            sql.SQL(
                "DO $$ BEGIN"
                " IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {name}) THEN"
                " CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;"
                " END IF; END $$"
            ).format(name=sql.Literal(RUNTIME_GROUP_ROLE), role=group_role)
        )
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
        verb = sql.SQL("ALTER ROLE" if exists else "CREATE ROLE")
        conn.execute(
            sql.SQL("{verb} {role} LOGIN {attributes} PASSWORD {password}").format(
                verb=verb,
                role=login_role,
                attributes=attributes,
                password=sql.Literal(password),
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


def main() -> int:
    settings = DatabaseSettings()
    try:
        bootstrap_runtime_role(settings.migration_database_url, settings.database_url)
    except (BootstrapError, psycopg.Error) as exc:
        # psycopg errors never include the connection password.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Runtime role {make_url(settings.database_url).username} is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
