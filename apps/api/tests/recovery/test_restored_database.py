"""A restored logical backup is complete and keeps every M1-06 protection.

Runs against the disposable source and restored databases created by
``scripts/verify-backup-restore.sh``. The script has already applied the shared
catalog assertions (scripts/lib/schema-assertions.sh), checked the Alembic head
and run ``alembic check`` on the restored database; this suite compares the
restored database with its source in full and proves Row-Level Security still
isolates tenants for the API runtime role.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.models import AuthenticatedCompanyContext
from app.db.runtime_role import check_runtime_role
from app.repositories import case_subjects, cases
from app.tenancy.scope import open_company_scope
from tests.recovery import fixture_data as data
from tests.recovery.conftest import RecoveryDatabases

API_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_GROUP_ROLE = "heroos_app_runtime"
OPERATOR_GROUP_ROLE = "heroos_identity_operator"
RLS_VIOLATION = "42501"
TENANT_TABLES = {
    "companies": "id",
    "memberships": "company_id",
    "company_blueprints": "company_id",
    "case_subjects": "company_id",
    "cases": "company_id",
}
APPLICATION_TABLES = (
    *TENANT_TABLES,
    "users",
    "user_identities",
    "identity_events",
    "membership_events",
)

# Catalog views of everything a restore must reproduce exactly.
CATALOG_QUERIES = {
    "tables": """
        SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
        WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')
        ORDER BY relname
    """,
    "columns": """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns WHERE table_schema = 'public'
        ORDER BY table_name, column_name
    """,
    "constraints": """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' ORDER BY 1, 2
    """,
    "policies": """
        SELECT tablename, policyname, permissive, roles::text, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public' ORDER BY 1, 2
    """,
    "functions": """
        SELECT proname, pg_get_functiondef(oid), prosecdef FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace ORDER BY 1
    """,
    "runtime_grants": f"""
        SELECT table_name, privilege_type FROM information_schema.role_table_grants
        WHERE grantee = '{RUNTIME_GROUP_ROLE}' ORDER BY 1, 2
    """,
    "column_grants": f"""
        SELECT grantee, table_name, column_name, privilege_type
        FROM information_schema.column_privileges
        WHERE grantee IN ('{RUNTIME_GROUP_ROLE}', '{OPERATOR_GROUP_ROLE}') ORDER BY 1, 2, 3, 4
    """,
    "operator_grants": f"""
        SELECT table_name, privilege_type FROM information_schema.role_table_grants
        WHERE grantee = '{OPERATOR_GROUP_ROLE}' ORDER BY 1, 2
    """,
    "triggers": """
        SELECT event_object_table, trigger_name, event_manipulation, action_timing,
               action_statement
        FROM information_schema.triggers WHERE trigger_schema = 'public' ORDER BY 1, 2, 3
    """,
    "function_acl": """
        SELECT proname, proacl::text, prosecdef, proconfig::text FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace ORDER BY 1
    """,
    "alembic_version": "SELECT version_num FROM alembic_version",
}


def snapshot(engine: Engine, query: str) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(query))]


def table_rows(engine: Engine, table: str) -> list[str]:
    assert table in APPLICATION_TABLES
    with engine.connect() as connection:
        return list(
            connection.scalars(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY t.id"))
        )


def context(company: uuid.UUID, user: uuid.UUID, membership: uuid.UUID, identity: uuid.UUID) -> Any:
    return AuthenticatedCompanyContext(
        user_id=user,
        company_id=company,
        membership_id=membership,
        identity_id=identity,
    )


CONTEXT_A = context(data.COMPANY_A, data.USER_A, data.MEMBERSHIP_A, data.IDENTITY_A)
CONTEXT_B = context(data.COMPANY_B, data.USER_B, data.MEMBERSHIP_B, data.IDENTITY_B)


# Completeness ------------------------------------------------------------------


@pytest.mark.parametrize("table", APPLICATION_TABLES)
def test_restored_rows_identical_to_source(
    source_admin: Engine, restored_admin: Engine, table: str
) -> None:
    source = table_rows(source_admin, table)

    assert source, f"source {table} was not seeded"
    assert table_rows(restored_admin, table) == source


def test_restored_data_matches_synthetic_dataset(restored_admin: Engine) -> None:
    for table, column in TENANT_TABLES.items():
        rows = snapshot(restored_admin, f"SELECT {column}, id FROM {table}")
        owners: dict[uuid.UUID, set[uuid.UUID]] = {}
        for owner, row_id in rows:
            owners.setdefault(owner, set()).add(row_id)
        assert owners == data.EXPECTED_ROWS[table], table


@pytest.mark.parametrize("view", CATALOG_QUERIES)
def test_restored_catalog_identical_to_source(
    source_admin: Engine, restored_admin: Engine, view: str
) -> None:
    source = snapshot(source_admin, CATALOG_QUERIES[view])

    assert source, f"source has no {view}"
    assert snapshot(restored_admin, CATALOG_QUERIES[view]) == source


def test_restored_revision_is_alembic_head(restored_admin: Engine) -> None:
    head = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini"))).get_current_head()

    assert snapshot(restored_admin, CATALOG_QUERIES["alembic_version"]) == [(head,)]


# Security controls survive the restore ---------------------------------------------


def test_restored_rls_and_policies(restored_admin: Engine) -> None:
    rls = {
        name for name, enabled, _ in snapshot(restored_admin, CATALOG_QUERIES["tables"]) if enabled
    }
    assert rls == set(TENANT_TABLES) | {
        "membership_events",
        "users",
        "user_identities",
        "identity_events",
    }
    policies = snapshot(restored_admin, CATALOG_QUERIES["policies"])
    tenant = {**TENANT_TABLES, "membership_events": "company_id"}
    assert {(table, policy) for table, policy, *_ in policies} == {
        *((table, "tenant_isolation") for table in tenant),
        ("memberships", "lifecycle_active"),
        ("users", "users_runtime_read"),
        ("users", "users_operator"),
        ("user_identities", "identities_runtime_read"),
        ("user_identities", "identities_operator"),
    }
    for table, name, permissive, roles, command, qual, with_check in policies:
        if name == "tenant_isolation":
            expected = f"({tenant[table]} = heroos_current_company_id())"
            assert (permissive, roles, command, qual, with_check) == (
                "PERMISSIVE",
                "{public}",
                "ALL",
                expected,
                expected,
            )
        elif name == "lifecycle_active":
            assert (permissive, roles, command) == ("RESTRICTIVE", "{heroos_app_runtime}", "SELECT")
        elif name.endswith("_runtime_read"):
            assert (permissive, roles, command) == ("PERMISSIVE", "{heroos_app_runtime}", "SELECT")
        else:
            assert (permissive, roles, command) == (
                "PERMISSIVE",
                "{heroos_identity_operator}",
                "ALL",
            )


def test_restored_tenant_context_function(restored_admin: Engine) -> None:
    ((definition, security_definer),) = snapshot(
        restored_admin,
        "SELECT pg_get_functiondef(oid), prosecdef FROM pg_proc "
        "WHERE proname = 'heroos_current_company_id'",
    )
    assert security_definer is False
    assert "NULLIF(pg_catalog.current_setting('heroos.company_id', true), '')::uuid" in definition


def test_restored_ownership_and_runtime_grants(
    restored_admin: Engine, recovery: RecoveryDatabases
) -> None:
    owners = snapshot(
        restored_admin,
        "SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class "
        "WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')",
    )
    # Restored with --no-owner as the migration/admin role; never the runtime role.
    assert owners == [(recovery.admin_role,)]
    grants = snapshot(restored_admin, CATALOG_QUERIES["runtime_grants"])
    expected = {
        (table, privilege)
        for table in TENANT_TABLES
        if table != "memberships"
        for privilege in ("DELETE", "INSERT", "SELECT", "UPDATE")
    } | {("memberships", "SELECT"), ("users", "SELECT"), ("user_identities", "SELECT")}
    assert set(grants) == expected
    # The identity operator's table and column grants survive the restore too.
    assert set(snapshot(restored_admin, CATALOG_QUERIES["operator_grants"])) == {
        ("users", "SELECT"),
        ("users", "INSERT"),
        ("user_identities", "SELECT"),
        ("user_identities", "INSERT"),
        ("memberships", "SELECT"),
        ("memberships", "INSERT"),
    }


def test_runtime_role_passes_startup_guard_on_restored_database(restored_runtime: Engine) -> None:
    with restored_runtime.connect() as connection:
        check_runtime_role(connection)


def test_restored_database_without_tenant_context_shows_nothing(
    restored_runtime: Engine,
) -> None:
    with restored_runtime.connect() as connection:
        for table in TENANT_TABLES:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table


@pytest.mark.parametrize(
    ("ctx", "own", "other"),
    [(CONTEXT_A, data.COMPANY_A, data.COMPANY_B), (CONTEXT_B, data.COMPANY_B, data.COMPANY_A)],
)
def test_restored_database_isolates_tenants(
    restored_runtime: Engine,
    ctx: AuthenticatedCompanyContext,
    own: uuid.UUID,
    other: uuid.UUID,
) -> None:
    with Session(restored_runtime) as session:
        scope = open_company_scope(session, ctx)
        # RLS alone: unfiltered queries see only the scope's own rows.
        for table, column in TENANT_TABLES.items():
            visible = set(session.scalars(text(f"SELECT {column} FROM {table}")))
            assert visible == {own}, table
        # Repositories on top: another Company's IDs are simply not found.
        other_case = data.CASE_B if other == data.COMPANY_B else data.CASE_A
        assert cases.get_case(scope, other_case) is None
        assert [case.company_id for case in cases.list_cases(scope)] == [own]
        session.rollback()


def test_restored_database_rejects_cross_tenant_writes(restored_runtime: Engine) -> None:
    with Session(restored_runtime) as session:
        open_company_scope(session, CONTEXT_A)
        with pytest.raises(DBAPIError) as exc_info:
            session.execute(
                text(
                    "INSERT INTO case_subjects (id, company_id, subject_type, display_name) "
                    "VALUES (:id, :company, 'employee', 'cross-tenant attempt')"
                ),
                {"id": uuid.uuid4(), "company": data.COMPANY_B},
            )
        assert getattr(exc_info.value.orig, "sqlstate", None) == RLS_VIOLATION
        session.rollback()

    with Session(restored_runtime) as session:
        scope = open_company_scope(session, CONTEXT_A)
        # A same-Company write still works, and the context is transaction-local.
        subject = case_subjects.create_case_subject(
            scope, subject_type="employee", display_name="post-restore write"
        )
        assert subject.company_id == data.COMPANY_A
        session.rollback()
        assert session.scalar(text("SELECT current_setting('heroos.company_id', true)")) in {
            None,
            "",
        }
