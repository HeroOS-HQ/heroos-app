"""Role-separation and inherited-privilege hardening (M1-10B independent review).

Deliberately creates the dangerous configurations, then proves the migrations
and the role bootstrap refuse them without leaving partial changes:

- runtime/operator group inheritance in either direction, or a login in both;
- Supabase-style default privileges that would grant every new table to API
  roles (``anon``, ``authenticated``, ``service_role``).

Cluster-wide changes (roles, group memberships) are reverted in ``finally``.
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from scripts.bootstrap_runtime_role import (
    BootstrapError,
    bootstrap_operator_role,
    bootstrap_runtime_role,
)
from tests.tenant_isolation.conftest import TenantDatabase, disposable_database, run_alembic

PRE_B1 = "97d4200fe7a2"
B1A = "b8a11c15ed91"
B1B = "09cb5ec569b9"
RUNTIME = "heroos_app_runtime"
OPERATOR = "heroos_identity_operator"
NEW_TABLES = ("user_identities", "identity_events", "membership_events")
ALL_TABLE_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER"


@contextmanager
def cluster(tenant_database: TenantDatabase) -> Iterator[Engine]:
    """Autocommit admin connection to the maintenance database (cluster-wide DDL)."""
    engine = create_engine(
        make_url(tenant_database.admin_url).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        yield engine
    finally:
        engine.dispose()


def execute(url: str, *statements: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(text(statement))
    finally:
        engine.dispose()


def scalar(url: str, sql: str, **params: object) -> object:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()
    finally:
        engine.dispose()


def revision(url: str) -> object:
    return scalar(url, "SELECT version_num FROM alembic_version")


# --- Conflicting role relationships ------------------------------------------------------


@contextmanager
def conflict(tenant_database: TenantDatabase, kind: str) -> Iterator[None]:
    """Create one forbidden relationship for the duration of the block."""
    login = f"heroos_conflict_{secrets.token_hex(4)}"
    setup = {
        "runtime-inherits-operator": [f"GRANT {OPERATOR} TO {RUNTIME}"],
        "operator-inherits-runtime": [f"GRANT {RUNTIME} TO {OPERATOR}"],
        "login-in-both": [
            f"CREATE ROLE {login} LOGIN",
            f"GRANT {RUNTIME} TO {login}",
            f"GRANT {OPERATOR} TO {login}",
        ],
    }[kind]
    teardown = {
        "runtime-inherits-operator": [f"REVOKE {OPERATOR} FROM {RUNTIME}"],
        "operator-inherits-runtime": [f"REVOKE {RUNTIME} FROM {OPERATOR}"],
        "login-in-both": [f"DROP ROLE IF EXISTS {login}"],
    }[kind]
    with cluster(tenant_database) as engine:
        with engine.connect() as conn:
            for statement in setup:
                conn.execute(text(statement))
        try:
            yield
        finally:
            with engine.connect() as conn:
                for statement in teardown:
                    conn.execute(text(statement))


CONFLICTS = ["runtime-inherits-operator", "operator-inherits-runtime", "login-in-both"]


@pytest.mark.parametrize("kind", CONFLICTS)
def test_b1a_refuses_role_relationships_joining_runtime_and_operator(
    tenant_database: TenantDatabase, kind: str
) -> None:
    with disposable_database(tenant_database, "rolea") as admin_url:
        assert run_alembic(admin_url, "upgrade", PRE_B1).returncode == 0
        with conflict(tenant_database, kind):
            result = run_alembic(admin_url, "upgrade", B1A)
        assert result.returncode != 0
        assert "remove it first" in result.stderr or "must be an unprivileged" in result.stderr
        assert revision(admin_url) == PRE_B1
        # Without the conflict the same database migrates normally.
        assert run_alembic(admin_url, "upgrade", "head").returncode == 0


@pytest.mark.parametrize("kind", CONFLICTS)
def test_b1b_refuses_to_grant_the_operator_while_roles_are_joined(
    tenant_database: TenantDatabase, kind: str
) -> None:
    with disposable_database(tenant_database, "roleb") as admin_url:
        assert run_alembic(admin_url, "upgrade", B1A).returncode == 0
        with conflict(tenant_database, kind):
            result = run_alembic(admin_url, "upgrade", B1B)
        assert result.returncode != 0
        assert "remove it first" in result.stderr
        assert revision(admin_url) == B1A


def _role_state(admin_url: str, login: str) -> tuple[object, ...]:
    engine = create_engine(admin_url)
    try:
        with engine.connect() as conn:
            return tuple(
                conn.execute(
                    text(
                        "SELECT a.rolpassword, a.rolcanlogin, "
                        "pg_has_role(a.oid, :runtime, 'MEMBER'), "
                        "pg_has_role(a.oid, :operator, 'MEMBER') "
                        "FROM pg_authid a WHERE a.rolname = :login"
                    ),
                    {"login": login, "runtime": RUNTIME, "operator": OPERATOR},
                ).one()
            )
    finally:
        engine.dispose()


def _login_url(tenant_database: TenantDatabase, login: str) -> tuple[str, str]:
    password = secrets.token_hex(32)
    url = (
        make_url(tenant_database.admin_url)
        .set(username=login, password=password)
        .render_as_string(hide_password=False)
    )
    return url, password


@pytest.mark.parametrize(
    ("existing_group", "bootstrap"),
    [
        pytest.param(OPERATOR, "runtime", id="operator-member-bootstrapped-as-runtime"),
        pytest.param(RUNTIME, "operator", id="runtime-member-bootstrapped-as-operator"),
    ],
)
def test_bootstrap_refuses_a_conflicting_login_and_changes_nothing(
    tenant_database: TenantDatabase, existing_group: str, bootstrap: str
) -> None:
    prefix = "heroos_app_t_" if bootstrap == "runtime" else "heroos_op_t_"
    login = f"{prefix}{secrets.token_hex(4)}"
    url, _ = _login_url(tenant_database, login)
    with cluster(tenant_database) as engine:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE {login} LOGIN"))
            conn.execute(text(f"GRANT {existing_group} TO {login}"))
        try:
            before = _role_state(tenant_database.admin_url, login)
            run = bootstrap_runtime_role if bootstrap == "runtime" else bootstrap_operator_role
            with pytest.raises(BootstrapError, match="is a member of"):
                run(tenant_database.admin_url, url)
            # Refused before any change: password, login flag and memberships intact.
            assert _role_state(tenant_database.admin_url, login) == before
        finally:
            with engine.connect() as conn:
                conn.execute(text(f"DROP ROLE IF EXISTS {login}"))


def test_bootstrap_refuses_joined_groups_without_creating_the_login(
    tenant_database: TenantDatabase,
) -> None:
    login = f"heroos_app_t_{secrets.token_hex(4)}"
    url, _ = _login_url(tenant_database, login)
    with (
        conflict(tenant_database, "runtime-inherits-operator"),
        pytest.raises(BootstrapError, match="must not inherit"),
    ):
        bootstrap_runtime_role(tenant_database.admin_url, url)
    assert (
        scalar(
            tenant_database.admin_url, "SELECT count(*) FROM pg_roles WHERE rolname = :r", r=login
        )
        == 0
    )


# --- Inherited default privileges (Supabase-style) -----------------------------------------


def test_new_objects_shed_default_privileges_granted_to_other_roles(
    tenant_database: TenantDatabase,
) -> None:
    # Simulates Supabase, where the schema owner's default privileges grant every
    # new table, sequence and function to the API roles. Disposable names: the
    # real anon/authenticated/service_role are never created or touched here.
    suffix = secrets.token_hex(4)
    roles = [f"heroos_sim_{name}_{suffix}" for name in ("anon", "authenticated", "service")]
    with cluster(tenant_database) as engine:
        with engine.connect() as conn:
            for role in roles:
                conn.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        try:
            with disposable_database(tenant_database, "acl") as admin_url:
                grantees = ", ".join(roles)
                execute(
                    admin_url,
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {grantees}",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT ALL ON FUNCTIONS TO {grantees}",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    f"GRANT ALL ON SEQUENCES TO {grantees}",
                )
                result = run_alembic(admin_url, "upgrade", "head")
                assert result.returncode == 0, result.stderr

                for role in roles:
                    for table in NEW_TABLES:
                        assert not scalar(
                            admin_url,
                            f"SELECT has_table_privilege(:r, 'public.{table}', "
                            f"'{ALL_TABLE_PRIVILEGES}')",
                            r=role,
                        ), (role, table)
                    assert not scalar(
                        admin_url,
                        "SELECT bool_or(has_function_privilege(:r, p.oid, 'EXECUTE')) "
                        "FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace "
                        "AND p.proname LIKE 'heroos_%' "
                        "AND p.proname <> 'heroos_current_company_id'",
                        r=role,
                    ), role
                # The intended grants survive.
                assert scalar(
                    admin_url,
                    "SELECT has_table_privilege(:r, 'public.user_identities', 'SELECT')",
                    r=RUNTIME,
                )
        finally:
            with engine.connect() as conn:
                for role in roles:
                    conn.execute(text(f"DROP ROLE IF EXISTS {role}"))


def test_b1a_refuses_well_known_supabase_api_roles_with_table_access(
    tenant_database: TenantDatabase,
) -> None:
    with cluster(tenant_database) as engine:
        with engine.connect() as conn:
            if conn.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname = 'anon'")):
                pytest.skip("an anon role already exists in this cluster; not touching it")
            conn.execute(text("CREATE ROLE anon NOLOGIN"))
        try:
            with disposable_database(tenant_database, "anon") as admin_url:
                assert run_alembic(admin_url, "upgrade", PRE_B1).returncode == 0
                execute(admin_url, "GRANT SELECT ON users TO anon")
                result = run_alembic(admin_url, "upgrade", B1A)
                assert result.returncode != 0
                assert "anon, authenticated or service_role" in result.stderr
                assert revision(admin_url) == PRE_B1
        finally:
            with engine.connect() as conn:
                conn.execute(text("DROP ROLE IF EXISTS anon"))
