"""Startup check that the API's database role is subject to Row-Level Security.

Superusers, BYPASSRLS roles and table owners skip RLS. Connecting the API as any
of them would silently remove the database tenant-isolation layer, so the API
refuses to start instead.
"""

from sqlalchemy import Connection, Engine, text


class UnsafeDatabaseRoleError(RuntimeError):
    """The API database role could bypass Row-Level Security."""


# pg_has_role(..., 'MEMBER') is true for the role itself and for every role it
# can SET ROLE to, so privileges reachable through membership are included.
_ROLE_CHECK = text(
    """
    SELECT
        EXISTS (
            SELECT FROM pg_roles r
            WHERE (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole)
              AND pg_has_role(current_user, r.oid, 'MEMBER')
        ) AS privileged,
        EXISTS (
            SELECT FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p')
              AND pg_has_role(current_user, c.relowner, 'MEMBER')
        ) AS owns_tables
    """
)


def check_runtime_role(connection: Connection) -> None:
    """Raise unless the connected role is unprivileged and owns no tables."""
    row = connection.execute(_ROLE_CHECK).one()
    if row.privileged:
        raise UnsafeDatabaseRoleError(
            "DATABASE_URL role is (or can become) SUPERUSER, BYPASSRLS or CREATEROLE; "
            "the API must connect as the RLS-restricted runtime role"
        )
    if row.owns_tables:
        raise UnsafeDatabaseRoleError(
            "DATABASE_URL role owns (or can become the owner of) application tables; "
            "the API must connect as the RLS-restricted runtime role"
        )


def verify_runtime_role(engine: Engine) -> None:
    with engine.connect() as connection:
        check_runtime_role(connection)
