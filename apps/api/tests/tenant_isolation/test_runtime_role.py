"""The API runtime role is actually subject to RLS, and RLS is configured as designed.

Evidence comes from the PostgreSQL catalog and from attempting privileged
operations as the runtime role, not from trusting the role-creation statements.
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from app.db.runtime_role import UnsafeDatabaseRoleError, check_runtime_role
from tests.tenant_isolation.conftest import (
    ASSISTANT_TABLES,
    DISPOSABLE_RUNTIME_ROLE,
    TENANT_AUDIT_TABLES,
    TENANT_TABLES,
    WORKFLOW_TABLES,
    TenantDatabase,
)

RUNTIME_GROUP_ROLE = "heroos_app_runtime"
OPERATOR_GROUP_ROLE = "heroos_identity_operator"

# Tables without RLS, each for a documented reason. Every other table in
# `public` must have RLS: a new private table (e.g. an M2 workflow entity) that
# forgets its policy fails test_every_table_has_rls_unless_explicitly_exempt.
RLS_EXEMPT_TABLES = {
    "alembic_version": "migration bookkeeping; runtime role has no privileges",
}
# Global identity tables (no company_id; ADR-008): RLS with lifecycle policies
# per role instead of a tenant policy.
LIFECYCLE_TABLES = {
    "users": ("users_operator", "users_runtime_read"),
    "user_identities": ("identities_operator", "identities_runtime_read"),
}
# Owner-only: RLS enabled with no policy at all (nobody else may read or write).
OWNER_ONLY_TABLES = {"identity_events"}


def test_runtime_engine_connects_as_runtime_role(
    runtime_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with runtime_engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == tenant_database.runtime_role


def test_suite_never_manages_the_shared_runtime_role(tenant_database: TenantDatabase) -> None:
    # Roles are cluster-wide: bootstrapping `heroos_app` here would reset the
    # live API credential (docs/operations/database-credentials.md).
    assert tenant_database.runtime_role != "heroos_app"
    assert DISPOSABLE_RUNTIME_ROLE.fullmatch(tenant_database.runtime_role)


def test_runtime_password_stored_as_client_side_scram_verifier(
    admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with admin_engine.connect() as conn:
        is_scram = conn.scalar(
            text("SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname = :name"),
            {"name": tenant_database.runtime_role},
        )

    assert is_scram is True


def test_runtime_role_rejects_a_wrong_password(tenant_database: TenantDatabase) -> None:
    wrong = make_url(tenant_database.runtime_url).set(password=secrets.token_hex(32))
    engine = create_engine(wrong, poolclass=NullPool)
    try:
        with pytest.raises(OperationalError), engine.connect():
            pass
    finally:
        engine.dispose()


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
        *[
            (table, {"SELECT", "INSERT", "UPDATE", "DELETE"})
            for table in ("case_subjects", "cases")
        ],
        # Company registration is operator-only (M1-10C): no INSERT or DELETE.
        ("companies", {"SELECT", "UPDATE"}),
        # INSERT and UPDATE are column-level (below): never the jurisdiction
        # confirmation.
        ("company_blueprints", {"SELECT", "DELETE"}),
        # Granting Company access or a role is provisioning: operator-only (ADR-008).
        ("memberships", {"SELECT"}),
        # Identity lookup only: no binding, reassignment or suspension.
        ("users", {"SELECT"}),
        ("user_identities", {"SELECT"}),
        # Workflow entities (M2-01): append-only, never deleted (PRIV-020). The
        # instance's revision is updatable column by column (below).
        ("workflow_instances", {"SELECT", "INSERT"}),
        ("workflow_submissions", {"SELECT", "INSERT"}),
        ("case_facts", {"SELECT", "INSERT"}),
        # Intake evaluations (M2-02): append-only trace, one row per save.
        ("workflow_evaluations", {"SELECT", "INSERT"}),
        # Progress events (M2-03): append-only, one row per decision.
        ("workflow_progress_events", {"SELECT", "INSERT"}),
        # Decision records (M2-04): append-only; corrections are new rows.
        ("workflow_decision_records", {"SELECT", "INSERT"}),
        # Ask HeroOS conversations (M2-NEW-07): append-only; a conversation's own
        # state is updatable column by column (below).
        ("assistant_conversations", {"SELECT", "INSERT"}),
        ("assistant_turns", {"SELECT", "INSERT"}),
        ("assistant_messages", {"SELECT", "INSERT"}),
        ("assistant_turn_evaluations", {"SELECT", "INSERT"}),
        # Audit is written only by owner-run triggers.
        ("identity_events", set()),
        ("membership_events", set()),
        ("company_events", set()),
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


# Every Blueprint column except the trusted jurisdiction confirmation (M1-10C).
RUNTIME_BLUEPRINT_COLUMNS = {
    "id",
    "company_id",
    "legal_name",
    "primary_jurisdiction",
    "industry",
    "employee_count",
    "licensing_location",
    "licensing_authority",
    "created_at",
    "updated_at",
    # M2-NEW-03 (D5): the company context.
    "website_url",
    "company_summary",
    "policies_exist",
    "policy_context",
    "hr_support",
    "hr_support_notes",
    "primary_contact_membership_id",
}
CONFIRMATION_COLUMNS = {
    "employment_jurisdiction",
    "confirmed_licensing_location",
    "confirmed_licensing_authority",
    "jurisdiction_confirmed_at",
}


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE"])
def test_runtime_role_writes_every_blueprint_column_except_the_confirmation(
    admin_engine: Engine, tenant_database: TenantDatabase, privilege: str
) -> None:
    with admin_engine.connect() as conn:
        columns = set(
            conn.scalars(
                text(
                    "SELECT attname FROM pg_attribute "
                    "WHERE attrelid = 'company_blueprints'::regclass "
                    "AND attnum > 0 AND NOT attisdropped"
                )
            )
        )
        writable = {
            column
            for column in columns
            if conn.scalar(
                text(
                    "SELECT has_column_privilege(:role, 'company_blueprints', :column, :privilege)"
                ),
                {"role": tenant_database.runtime_role, "column": column, "privilege": privilege},
            )
        }

    assert columns == RUNTIME_BLUEPRINT_COLUMNS | CONFIRMATION_COLUMNS
    assert writable == RUNTIME_BLUEPRINT_COLUMNS


def test_runtime_role_holds_no_column_privilege_on_memberships(
    admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    # No column-level path around the table-level SELECT-only grant: in
    # particular no UPDATE (role), so no self-promotion.
    with admin_engine.connect() as conn:
        granted = conn.scalars(
            text(
                "SELECT attname || ':' || privilege FROM pg_attribute, "
                "unnest(ARRAY['INSERT', 'UPDATE', 'REFERENCES']) AS privilege "
                "WHERE attrelid = 'memberships'::regclass AND attnum > 0 AND NOT attisdropped "
                "AND has_column_privilege(:role, 'memberships', attname, privilege)"
            ),
            {"role": tenant_database.runtime_role},
        ).all()
    assert granted == []


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


def test_runtime_role_cannot_assume_the_admin_role(
    runtime_engine: Engine, admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    # The migration/admin role is whatever the suite connects as: `heroos` locally
    # and in CI, `supabase_admin` on the Supabase image. Hardcoding the name made
    # PostgreSQL answer 22023 (undefined role) instead of 42501 on other clusters,
    # which proves nothing about privileges.
    admin_role = make_url(tenant_database.admin_url).username
    assert admin_role
    with admin_engine.connect() as conn:
        # Ground truth: the role exists, is the one connected, and owns the schema.
        assert conn.scalar(text("SELECT current_user")) == admin_role
        assert conn.scalar(text("SELECT tableowner FROM pg_tables WHERE tablename = 'cases'")) == (
            admin_role
        )

    quoted = runtime_engine.dialect.identifier_preparer.quote(admin_role)
    with runtime_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(text(f"SET ROLE {quoted}"))

    # 42501 insufficient_privilege: the role exists and the runtime role may not become it.
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
    assert {name for name, enabled in tables.items() if enabled} == (
        set(TENANT_TABLES)
        | set(TENANT_AUDIT_TABLES)
        | set(WORKFLOW_TABLES)
        | set(ASSISTANT_TABLES)
        | set(LIFECYCLE_TABLES)
        | OWNER_ONLY_TABLES
    )


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

    tenant_tables = {**TENANT_TABLES, **TENANT_AUDIT_TABLES, **WORKFLOW_TABLES, **ASSISTANT_TABLES}
    permissive_tenant = [p for p in policies if p.tablename in tenant_tables]
    permissive_tenant = [p for p in permissive_tenant if p.permissive == "PERMISSIVE"]
    # A second permissive policy would be OR-ed in and could only widen access.
    assert sorted(p.tablename for p in permissive_tenant) == sorted(tenant_tables)
    for policy in permissive_tenant:
        column = tenant_tables[policy.tablename]
        expected = f"({column} = heroos_current_company_id())"
        assert policy.policyname == "tenant_isolation"
        assert policy.cmd == "ALL"
        assert list(policy.roles) == ["public"]
        assert policy.qual == expected
        assert policy.with_check == expected

    # The only other tenant-table policy narrows the API role: a RESTRICTIVE
    # lifecycle filter, so it can never widen access.
    restrictive = [p for p in policies if p.permissive == "RESTRICTIVE"]
    assert [(p.tablename, p.policyname, p.cmd, list(p.roles), p.qual) for p in restrictive] == [
        (
            "memberships",
            "lifecycle_active",
            "SELECT",
            [RUNTIME_GROUP_ROLE],
            "((status)::text = 'active'::text)",
        )
    ]

    # Global identity tables: the API role reads active rows only; the operator
    # group manages lifecycle. No PUBLIC policy, nothing for any other role.
    lifecycle = {
        (p.tablename, p.policyname): p for p in policies if p.tablename in LIFECYCLE_TABLES
    }
    assert set(lifecycle) == {
        (table, name) for table, names in LIFECYCLE_TABLES.items() for name in names
    }
    for (_table, name), policy in lifecycle.items():
        assert policy.permissive == "PERMISSIVE"
        if name.endswith("_runtime_read"):
            assert (policy.cmd, list(policy.roles)) == ("SELECT", [RUNTIME_GROUP_ROLE])
            assert policy.qual == "((status)::text = 'active'::text)"
        else:
            assert (policy.cmd, list(policy.roles)) == ("ALL", [OPERATOR_GROUP_ROLE])
    assert {p.tablename for p in policies} == set(tenant_tables) | set(LIFECYCLE_TABLES)


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
