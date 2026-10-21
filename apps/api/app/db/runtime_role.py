"""Startup checks for the database roles HeroOS connects as, and the schema contract.

Superusers, BYPASSRLS roles and table owners skip RLS. Connecting the API as any
of them would silently remove the database tenant-isolation layer, so the API
refuses to start instead. The API also refuses an identity-operator login: the
operator credential never belongs in a running service (ADR-008).

The identity operator CLI runs the mirror-image check (``check_operator_role``):
an unprivileged member of ``heroos_identity_operator`` that is *not* an API
runtime role, so it can provision identities but cannot read HR data.

``heroos_schema_contract()`` tells code which schema is live (the runtime role
cannot read ``alembic_version``): 1 after migration B1a, 2 after B1b, 3 after
C1 (M1-10C: Company roles, registration and jurisdiction readiness), 4 after D1
(M2-01: workflow instances, submissions and facts), 5 after D2 (M2-02: intake
evaluations), 6 after D3 (M2-03: workflow progress events), 7 after D4 (M2-04:
employer decision records), 8 after D5 (M2-NEW-03: the Company Blueprint
context). The API needs at least 8; the operator needs exactly 8 (its own
grants are unchanged by D1 to D5, but it refuses any schema it was not written
against).
"""

from typing import Final

from sqlalchemy import Connection, Engine, Row, text
from sqlalchemy.exc import DBAPIError

RUNTIME_GROUP_ROLE: Final = "heroos_app_runtime"
OPERATOR_GROUP_ROLE: Final = "heroos_identity_operator"

# Schema the API needs (D5: the Company Blueprint context, on top of D4 decision
# records, D3 progress events, D2 intake evaluations, D1 workflow Cases and
# facts, C1 roles and jurisdiction readiness and B1a/B1b identities and lifecycle).
API_MINIMUM_SCHEMA_CONTRACT: Final = 8
# Schema the operator CLI needs exactly (C1 registration, role and jurisdiction
# confirmation grants on top of B1b provisioning; D1 to D5 add nothing for it).
OPERATOR_SCHEMA_CONTRACT: Final = 8


class UnsafeDatabaseRoleError(RuntimeError):
    """The database role could bypass Row-Level Security or holds the wrong capability."""


class IncompatibleSchemaError(RuntimeError):
    """The database schema is not the identity schema this code requires."""


# pg_has_role(..., 'MEMBER') is true for the role itself and for every role it
# can SET ROLE to, so privileges reachable through membership are included.
# Group roles are looked up by name so the check also runs on schemas where a
# group does not exist yet.
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
        ) AS owns_tables,
        EXISTS (
            SELECT FROM pg_roles r
            WHERE r.rolname = :operator_group
              AND pg_has_role(current_user, r.oid, 'MEMBER')
        ) AS operator,
        EXISTS (
            SELECT FROM pg_roles r
            WHERE r.rolname = :runtime_group
              AND pg_has_role(current_user, r.oid, 'MEMBER')
        ) AS runtime
    """
).bindparams(operator_group=OPERATOR_GROUP_ROLE, runtime_group=RUNTIME_GROUP_ROLE)


def _role_facts(connection: Connection) -> Row[tuple[bool, bool, bool, bool]]:
    return connection.execute(_ROLE_CHECK).one()


def check_runtime_role(connection: Connection) -> None:
    """Raise unless the connected role is an unprivileged, non-owner, non-operator role."""
    row = _role_facts(connection)
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
    if row.operator:
        raise UnsafeDatabaseRoleError(
            "DATABASE_URL role is an identity operator; the API must never hold the "
            "operator credential"
        )


def check_operator_role(connection: Connection) -> None:
    """Raise unless the connected role is a plain identity-operator login.

    Refuses the migration owner, superusers, BYPASSRLS/CREATEROLE roles and any
    role that is also an API runtime role (which would add HR data access).
    """
    row = _role_facts(connection)
    if row.privileged:
        raise UnsafeDatabaseRoleError(
            "operator role is (or can become) SUPERUSER, BYPASSRLS or CREATEROLE"
        )
    if row.owns_tables:
        raise UnsafeDatabaseRoleError(
            "operator role owns application tables; never use the migration owner"
        )
    if not row.operator:
        raise UnsafeDatabaseRoleError(f"operator login is not a member of {OPERATOR_GROUP_ROLE}")
    if row.runtime:
        raise UnsafeDatabaseRoleError(
            f"operator login must not be a member of {RUNTIME_GROUP_ROLE} (HR data access)"
        )


def schema_contract(connection: Connection) -> int:
    """The live identity schema contract; raises if the database has none."""
    try:
        with connection.begin_nested():
            value = connection.scalar(text("SELECT heroos_schema_contract()"))
    except DBAPIError:
        # Undefined function (pre-B1a schema) or no EXECUTE privilege.
        raise IncompatibleSchemaError(
            "heroos_schema_contract() is unavailable; apply the identity migrations"
        ) from None
    if not isinstance(value, int):
        raise IncompatibleSchemaError("heroos_schema_contract() returned no contract")
    return value


def check_schema_contract(connection: Connection, *, minimum: int, exact: bool = False) -> int:
    value = schema_contract(connection)
    if value < minimum or (exact and value != minimum):
        expected = f"exactly {minimum}" if exact else f"at least {minimum}"
        raise IncompatibleSchemaError(
            f"database identity schema contract is {value}; this code requires {expected}"
        )
    return value


def verify_runtime_role(engine: Engine) -> None:
    """API startup: a safe runtime role and a compatible identity schema."""
    with engine.connect() as connection:
        check_runtime_role(connection)
        check_schema_contract(connection, minimum=API_MINIMUM_SCHEMA_CONTRACT)
