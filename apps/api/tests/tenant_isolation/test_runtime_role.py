"""The API runtime role is actually subject to RLS, and RLS is configured as designed.

Evidence comes from the PostgreSQL catalog and from attempting privileged
operations as the runtime role, not from trusting the role-creation statements.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.db.runtime_role import UnsafeDatabaseRoleError, check_runtime_role
from tests.tenant_isolation.conftest import TENANT_TABLES, TenantDatabase

RUNTIME_GROUP_ROLE = "heroos_app_runtime"

# Tables without tenant RLS, each for a documented reason. Every other table in
# `public` must have RLS: a new private table (e.g. an M2 workflow entity) that
# forgets its policy fails test_every_table_has_rls_unless_explicitly_exempt.
RLS_EXEMPT_TABLES = {
    "users": "global identity reference; no company_id; runtime role may only SELECT",
    "alembic_version": "migration bookkeeping; runtime role has no privileges",
}


def test_runtime_engine_connects_as_runtime_role(
    runtime_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with runtime_engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == tenant_database.runtime_role


@pytest.mark.parametrize("role", ["login", "group"])
def test_runtime_roles_are_not_privileged(
    admin_engine: Engine, tenant_database: TenantDatabase, role: str
) -> None:
    name = tenant_database.runtime_role if role == "login" else RUNTIME_GROUP_ROLE
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin "
                "FROM pg_roles WHERE rolname = :name"
            ),
            {"name": name},
        ).one()

    assert row.rolsuper is False
    assert row.rolbypassrls is False
    assert row.rolcreaterole is False
    assert row.rolcreatedb is False
    assert row.rolcanlogin is (role == "login")


def test_runtime_role_cannot_become_a_privileged_role(
    admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with admin_engine.connect() as conn:
        reachable = conn.scalars(
            text(
                "SELECT r.rolname FROM pg_roles r "
                "WHERE (r.rolsuper OR r.rolbypassrls) AND pg_has_role(:name, r.oid, 'MEMBER')"
            ),
            {"name": tenant_database.runtime_role},
        ).all()
        member_of_group = conn.scalar(
            text("SELECT pg_has_role(:name, :group, 'MEMBER')"),
            {"name": tenant_database.runtime_role, "group": RUNTIME_GROUP_ROLE},
        )

    assert reachable == []
    assert member_of_group is True


def test_runtime_role_owns_no_tables(admin_engine: Engine, tenant_database: TenantDatabase) -> None:
    with admin_engine.connect() as conn:
        owners: dict[str, str] = dict(
            conn.execute(
                text(
                    "SELECT c.relname, pg_get_userbyid(c.relowner) FROM pg_class c "
                    "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
                )
            ).all()
        )
        owned_via_membership = conn.scalars(
            text(
                "SELECT c.relname FROM pg_class c "
                "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' "
                "AND pg_has_role(:name, c.relowner, 'MEMBER')"
            ),
            {"name": tenant_database.runtime_role},
        ).all()

    assert set(TENANT_TABLES) <= set(owners)
    for table in TENANT_TABLES:
        assert owners[table] not in (tenant_database.runtime_role, RUNTIME_GROUP_ROLE)
    assert owned_via_membership == []


def test_startup_guard_accepts_runtime_role_and_rejects_admin(
    runtime_engine: Engine, admin_engine: Engine
) -> None:
    with runtime_engine.connect() as conn:
        check_runtime_role(conn)

    with admin_engine.connect() as conn, pytest.raises(UnsafeDatabaseRoleError):
        check_runtime_role(conn)


@pytest.mark.parametrize(
    ("table", "allowed"),
    [
        *[(table, {"SELECT", "INSERT", "UPDATE", "DELETE"}) for table in TENANT_TABLES],
        ("users", {"SELECT"}),
        ("alembic_version", set()),
    ],
)
def test_runtime_role_has_only_required_table_privileges(
    admin_engine: Engine, tenant_database: TenantDatabase, table: str, allowed: set[str]
) -> None:
    privileges = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
    with admin_engine.connect() as conn:
        granted = {
            privilege
            for privilege in privileges
            if conn.scalar(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": tenant_database.runtime_role, "table": table, "privilege": privilege},
            )
        }

    # TRUNCATE in particular is never granted: it is not subject to RLS.
    assert granted == allowed


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("CREATE TABLE intruder (id int)", id="create-table"),
        pytest.param("ALTER TABLE cases DISABLE ROW LEVEL SECURITY", id="disable-rls"),
        pytest.param("ALTER TABLE cases NO FORCE ROW LEVEL SECURITY", id="alter-table"),
        pytest.param("DROP POLICY tenant_isolation ON cases", id="drop-policy"),
        pytest.param(
            "CREATE POLICY open_door ON cases FOR SELECT USING (true)", id="add-permissive-policy"
        ),
        pytest.param("TRUNCATE cases", id="truncate"),
        pytest.param("SELECT * FROM alembic_version", id="read-migration-state"),
        pytest.param(
            "CREATE OR REPLACE FUNCTION heroos_current_company_id() RETURNS uuid "
            "LANGUAGE sql AS $$ SELECT NULL::uuid $$",
            id="replace-context-function",
        ),
        pytest.param("SET ROLE heroos", id="set-role-admin"),
        pytest.param("CREATE ROLE intruder BYPASSRLS", id="create-role"),
    ],
)
def test_runtime_role_cannot_change_schema_or_security(
    runtime_engine: Engine, statement: str
) -> None:
    with runtime_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(text(statement))

    # 42501 insufficient_privilege / must be owner.
    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"


def test_disabling_row_security_errors_instead_of_bypassing(
    runtime_engine: Engine, tenants: object
) -> None:
    # row_security=off makes PostgreSQL raise rather than silently filter for a
    # role subject to RLS; it never turns RLS off.
    with runtime_engine.connect() as conn:
        conn.execute(text("SET LOCAL row_security = off"))
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text("SELECT count(*) FROM cases"))
        conn.rollback()

    assert getattr(exc_info.value.orig, "sqlstate", None) == "42501"


def test_every_table_has_rls_unless_explicitly_exempt(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        tables: dict[str, bool] = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')"
                )
            ).all()
        )

    without_rls = {name for name, enabled in tables.items() if not enabled}
    assert without_rls == set(RLS_EXEMPT_TABLES)
    assert {name for name, enabled in tables.items() if enabled} == set(TENANT_TABLES)


def test_each_tenant_table_has_exactly_one_permissive_policy_for_all_commands(
    admin_engine: Engine,
) -> None:
    with admin_engine.connect() as conn:
        policies = conn.execute(
            text(
                "SELECT tablename, policyname, permissive, roles, cmd, qual, with_check "
                "FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).all()

    # A second permissive policy would be OR-ed in and could only widen access.
    assert sorted(p.tablename for p in policies) == sorted(TENANT_TABLES)
    for policy in policies:
        column = TENANT_TABLES[policy.tablename]
        expected = f"({column} = heroos_current_company_id())"
        assert policy.policyname == "tenant_isolation"
        assert policy.permissive == "PERMISSIVE"
        assert policy.cmd == "ALL"
        assert list(policy.roles) == ["public"]
        assert policy.qual == expected
        assert policy.with_check == expected


def test_tenant_context_function_is_not_security_definer(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT prosecdef, provolatile FROM pg_proc "
                "WHERE proname = 'heroos_current_company_id'"
            )
        ).one()

    assert row.prosecdef is False
    assert row.provolatile == "s"


@pytest.mark.parametrize(("role", "starts"), [("runtime", True), ("admin", False)])
def test_api_refuses_to_start_with_a_role_that_bypasses_rls(
    monkeypatch: pytest.MonkeyPatch,
    runtime_engine: Engine,
    admin_engine: Engine,
    role: str,
    starts: bool,
) -> None:
    import app.main

    monkeypatch.setattr(app.main, "engine", runtime_engine if role == "runtime" else admin_engine)

    if starts:
        with TestClient(app.main.app) as client:
            assert client.get("/health").status_code == 200
    else:
        with pytest.raises(UnsafeDatabaseRoleError), TestClient(app.main.app):
            pass
