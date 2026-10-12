"""API runtime role vs identity operator role: least privilege, proven in PostgreSQL.

ADR-008: the internet-facing API role can only *look up* identities; only the
identity operator can provision, bind, suspend, revoke or reactivate; the
operator can never read HR data, hold the migration-owner capability, or be
used by the API. Every assertion attempts the operation as the real role.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.db.runtime_role import (
    UnsafeDatabaseRoleError,
    check_operator_role,
    check_runtime_role,
)
from tests.tenant_isolation.conftest import TEST_REFERENCE, TenantDatabase, Tenants

INSUFFICIENT_PRIVILEGE = "42501"
INVALID_PARAMETER = "22023"


def _sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


def _attempt(
    engine: Engine, statement: str, params: dict[str, Any], *, company: Any = None
) -> DBAPIError:
    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": TEST_REFERENCE}
        )
        if company is not None:
            conn.execute(
                text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(company)}
            )
        with pytest.raises(DBAPIError) as exc_info:
            conn.execute(text(statement), params)
        return exc_info.value


def _params(tenants: Tenants) -> dict[str, Any]:
    return {
        "user": tenants.a.user,
        "other_user": tenants.b.user,
        "identity": tenants.a.identity,
        "membership": tenants.a.membership,
        "company": tenants.a.company,
        "carol": tenants.carol,
    }


# --- The API runtime role cannot mutate identity, lifecycle or audit ----------------

RUNTIME_FORBIDDEN = [
    pytest.param("INSERT INTO users (id) VALUES (gen_random_uuid())", id="create-user"),
    pytest.param(
        "UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :user",
        id="suspend-user",
    ),
    pytest.param(
        "INSERT INTO user_identities (id, user_id, issuer, subject) "
        "VALUES (gen_random_uuid(), :user, 'urn:heroos:test', 'forged')",
        id="bind-identity",
    ),
    pytest.param(
        "UPDATE user_identities SET user_id = :other_user WHERE id = :identity",
        id="reassign-identity",
    ),
    pytest.param(
        "UPDATE user_identities SET status = 'active', revoked_at = NULL WHERE id = :identity",
        id="reactivate-identity",
    ),
    pytest.param(
        "INSERT INTO memberships (id, company_id, user_id) "
        "VALUES (gen_random_uuid(), :company, :carol)",
        id="grant-membership",
    ),
    pytest.param(
        "UPDATE memberships SET status = 'active', revoked_at = NULL WHERE id = :membership",
        id="reactivate-membership",
    ),
    pytest.param(
        "INSERT INTO identity_events (event_type, user_id, actor_kind, db_role, actor_reference) "
        "VALUES ('user_created', :user, 'owner', 'x', 'HER-1')",
        id="forge-identity-event",
    ),
    pytest.param("SELECT count(*) FROM identity_events", id="read-identity-events"),
    pytest.param("SELECT count(*) FROM membership_events", id="read-membership-events"),
    pytest.param("DELETE FROM user_identities", id="delete-identities"),
    pytest.param("SET ROLE heroos_identity_operator", id="become-operator"),
]


@pytest.mark.parametrize("statement", RUNTIME_FORBIDDEN)
def test_api_role_cannot_run_operator_mutations(
    runtime_engine: Engine, tenants: Tenants, statement: str
) -> None:
    error = _attempt(runtime_engine, statement, _params(tenants), company=tenants.a.company)
    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_api_role_sees_only_active_identities_users_and_memberships(
    runtime_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": TEST_REFERENCE}
        )
        conn.execute(
            text("UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :u"),
            {"u": tenants.a.user},
        )
        conn.execute(
            text(
                "UPDATE user_identities SET status = 'revoked', revoked_at = now() "
                "WHERE user_id = :u"
            ),
            {"u": tenants.b.user},
        )
        conn.execute(
            text("UPDATE memberships SET status = 'revoked', revoked_at = now() WHERE id = :m"),
            {"m": tenants.b.membership},
        )

    with runtime_engine.connect() as conn:
        # RLS alone (unfiltered SQL): the lifecycle is enforced for any API code.
        assert (
            conn.scalar(text("SELECT count(*) FROM users WHERE id = :u"), {"u": tenants.a.user})
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM user_identities WHERE user_id = :u"),
                {"u": tenants.b.user},
            )
            == 0
        )
        conn.execute(
            text("SELECT set_config('heroos.company_id', :c, true)"), {"c": str(tenants.b.company)}
        )
        assert conn.scalar(text("SELECT count(*) FROM memberships")) == 0


# --- The operator can provision, but nothing else ------------------------------------

OPERATOR_FORBIDDEN = [
    pytest.param("SELECT count(*) FROM cases", id="read-cases"),
    pytest.param("SELECT count(*) FROM case_subjects", id="read-case-subjects"),
    pytest.param("SELECT count(*) FROM company_blueprints", id="read-blueprints"),
    pytest.param("SELECT name FROM companies", id="read-company-names"),
    pytest.param("UPDATE companies SET name = 'x'", id="rename-company"),
    pytest.param(
        "UPDATE user_identities SET user_id = :other_user WHERE id = :identity",
        id="reassign-identity",
    ),
    pytest.param(
        "UPDATE user_identities SET subject = 'hijack' WHERE id = :identity", id="rewrite-subject"
    ),
    pytest.param(
        "UPDATE user_identities SET issuer = 'urn:heroos:x' WHERE id = :identity",
        id="rewrite-issuer",
    ),
    pytest.param(
        "UPDATE memberships SET user_id = :carol WHERE id = :membership", id="move-membership"
    ),
    pytest.param("DELETE FROM memberships WHERE id = :membership", id="delete-membership"),
    pytest.param("DELETE FROM user_identities WHERE id = :identity", id="delete-identity"),
    pytest.param("DELETE FROM users WHERE id = :user", id="delete-user"),
    pytest.param("TRUNCATE memberships", id="truncate"),
    pytest.param(
        "INSERT INTO identity_events (event_type, user_id, actor_kind, db_role, actor_reference) "
        "VALUES ('user_created', :user, 'owner', 'x', 'HER-1')",
        id="forge-identity-event",
    ),
    pytest.param("SELECT count(*) FROM identity_events", id="read-identity-events"),
    pytest.param("SELECT count(*) FROM alembic_version", id="read-migration-state"),
    pytest.param("SET ROLE heroos_app_runtime", id="become-api"),
    pytest.param("ALTER TABLE users DISABLE TRIGGER heroos_audit_users", id="disable-audit"),
    pytest.param("ALTER TABLE memberships DISABLE ROW LEVEL SECURITY", id="disable-rls"),
]


@pytest.mark.parametrize("statement", OPERATOR_FORBIDDEN)
def test_operator_role_is_confined_to_identity_provisioning(
    operator_engine: Engine, tenants: Tenants, statement: str
) -> None:
    error = _attempt(operator_engine, statement, _params(tenants), company=tenants.a.company)
    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE


def test_operator_cannot_write_another_companys_membership(
    operator_engine: Engine, tenants: Tenants
) -> None:
    error = _attempt(
        operator_engine,
        "INSERT INTO memberships (id, company_id, user_id) VALUES (gen_random_uuid(), :b, :carol)",
        {"b": tenants.b.company, "carol": tenants.carol},
        company=tenants.a.company,
    )
    assert _sqlstate(error) == INSUFFICIENT_PRIVILEGE
    assert "row-level security" in str(error.orig)


def test_changes_without_a_valid_reference_are_rejected_with_the_change(
    operator_engine: Engine, admin_engine: Engine, tenants: Tenants
) -> None:
    for reference in (
        None,
        "",
        "free text with a name",
        "alice@example.com",
        "alembic:b8a11c15ed91",
    ):
        with operator_engine.connect() as conn:
            if reference is not None:
                conn.execute(
                    text("SELECT set_config('heroos.actor_reference', :r, true)"), {"r": reference}
                )
            with pytest.raises(DBAPIError) as exc_info:
                conn.execute(
                    text(
                        "UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :u"
                    ),
                    {"u": tenants.a.user},
                )
        assert _sqlstate(exc_info.value) == INVALID_PARAMETER, reference

    with admin_engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT status FROM users WHERE id = :u"), {"u": tenants.a.user})
            == "active"
        )


def test_operator_changes_are_attributed_to_the_login_and_reference(
    operator_engine: Engine,
    admin_engine: Engine,
    tenant_database: TenantDatabase,
    tenants: Tenants,
) -> None:
    with operator_engine.begin() as conn:
        conn.execute(text("SELECT set_config('heroos.actor_reference', 'HER-231', true)"))
        conn.execute(
            text("UPDATE users SET status = 'suspended', suspended_at = now() WHERE id = :u"),
            {"u": tenants.a.user},
        )
        # Trying to impersonate another login changes nothing: session_user is recorded.
        conn.execute(text("SELECT set_config('heroos.db_role', 'someone_else', true)"))
        conn.execute(
            text("UPDATE users SET status = 'active', suspended_at = NULL WHERE id = :u"),
            {"u": tenants.a.user},
        )

    with admin_engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT event_type, actor_kind, db_role, actor_reference FROM identity_events "
                "WHERE user_id = :u AND actor_reference = 'HER-231'"
            ),
            {"u": tenants.a.user},
        ).all()
    assert sorted(events) == sorted(
        [
            ("user_suspended", "operator", tenant_database.operator_role, "HER-231"),
            ("user_reactivated", "operator", tenant_database.operator_role, "HER-231"),
        ]
    )


def test_audit_events_are_append_only_even_for_the_owner(
    admin_engine: Engine, tenants: Tenants
) -> None:
    for statement in ("UPDATE identity_events SET db_role = 'x'", "DELETE FROM identity_events"):
        with admin_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
            conn.execute(text(statement))
        assert "append-only" in str(exc_info.value.orig)


def test_identity_bindings_are_immutable_even_for_the_owner(
    admin_engine: Engine, tenants: Tenants
) -> None:
    with admin_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(text("SELECT set_config('heroos.actor_reference', 'HER-230', true)"))
        conn.execute(
            text("UPDATE user_identities SET user_id = :b WHERE id = :i"),
            {"b": tenants.b.user, "i": tenants.a.identity},
        )
    assert "immutable" in str(exc_info.value.orig)


# --- Login separation guards ------------------------------------------------------------


def test_startup_guards_keep_api_and_operator_credentials_apart(
    runtime_engine: Engine, operator_engine: Engine, admin_engine: Engine
) -> None:
    with runtime_engine.connect() as conn:
        check_runtime_role(conn)
        with pytest.raises(UnsafeDatabaseRoleError):
            check_operator_role(conn)
    with operator_engine.connect() as conn:
        check_operator_role(conn)
        with pytest.raises(UnsafeDatabaseRoleError, match="identity operator"):
            check_runtime_role(conn)
    with admin_engine.connect() as conn, pytest.raises(UnsafeDatabaseRoleError):
        check_operator_role(conn)


def test_api_refuses_to_start_with_the_operator_credential(
    monkeypatch: pytest.MonkeyPatch, operator_engine: Engine
) -> None:
    import app.main

    monkeypatch.setattr(app.main, "engine", operator_engine)
    with pytest.raises(UnsafeDatabaseRoleError), TestClient(app.main.app):
        pass


def test_operator_login_is_not_privileged_and_not_an_api_role(
    admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
                "pg_has_role(rolname, 'heroos_identity_operator', 'MEMBER') AS operator, "
                "pg_has_role(rolname, 'heroos_app_runtime', 'MEMBER') AS runtime "
                "FROM pg_roles WHERE rolname = :name"
            ),
            {"name": tenant_database.operator_role},
        ).one()
    assert (row.rolsuper, row.rolbypassrls, row.rolcreaterole, row.rolcreatedb) == (
        False,
        False,
        False,
        False,
    )
    assert (row.operator, row.runtime) == (True, False)


def test_audit_functions_are_pinned_and_not_callable_by_app_roles(
    admin_engine: Engine, tenant_database: TenantDatabase
) -> None:
    with admin_engine.connect() as conn:
        functions = conn.execute(
            text(
                "SELECT proname, prosecdef, proconfig, "
                "has_function_privilege(:runtime, oid, 'EXECUTE') AS runtime, "
                "has_function_privilege(:operator, oid, 'EXECUTE') AS operator "
                "FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
                "AND proname LIKE 'heroos_%' AND proname <> 'heroos_current_company_id'"
            ),
            {"runtime": tenant_database.runtime_role, "operator": tenant_database.operator_role},
        ).all()
    by_name = {f.proname: f for f in functions}
    for name in ("heroos_audit_identity_change", "heroos_audit_membership_change"):
        assert by_name[name].prosecdef is True
    for f in functions:
        if f.proname == "heroos_schema_contract":
            # A constant SQL function; the only one the app roles may call.
            assert (f.prosecdef, f.runtime, f.operator) == (False, True, True)
        else:
            assert f.proconfig == ['search_path=""'], f.proname
            assert (f.runtime, f.operator) == (False, False), f.proname


# --- Audit truncation and inherited privileges (independent review) ------------------


@pytest.mark.parametrize(
    "statement",
    [
        "TRUNCATE identity_events",
        "TRUNCATE membership_events",
        # Cascaded truncation reaches the audit tables too.
        "TRUNCATE users CASCADE",
        "TRUNCATE companies CASCADE",
    ],
)
def test_audit_events_refuse_truncate_even_for_the_owner(
    admin_engine: Engine, tenants: Tenants, statement: str
) -> None:
    with admin_engine.connect() as conn, pytest.raises(DBAPIError) as exc_info:
        conn.execute(text(statement))
    assert "append-only" in str(exc_info.value.orig)
    with admin_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM identity_events")) > 0


HEROOS_GROUPS = ("heroos_app_runtime", "heroos_identity_operator")


def test_no_role_outside_heroos_holds_table_privileges(admin_engine: Engine) -> None:
    # Portable: holds whether or not Supabase's anon/authenticated/service_role
    # (or any other platform role) exist.
    with admin_engine.connect() as conn:
        grantees = set(
            conn.scalars(
                text(
                    "SELECT DISTINCT CASE WHEN a.grantee = 0 THEN 'PUBLIC' "
                    "ELSE pg_get_userbyid(a.grantee) END "
                    "FROM pg_class c, aclexplode(c.relacl) a "
                    "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') "
                    "AND a.grantee <> c.relowner"
                )
            )
        )
        column_grantees = set(
            conn.scalars(
                text(
                    "SELECT DISTINCT grantee FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' AND grantee <> "
                    "(SELECT pg_get_userbyid(relowner) FROM pg_class "
                    " WHERE oid = 'public.users'::regclass)"
                )
            )
        )
    assert grantees <= set(HEROOS_GROUPS)
    assert column_grantees <= set(HEROOS_GROUPS)


def test_new_identity_objects_hold_only_the_intended_grants(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        table_acl = set(
            conn.execute(
                text(
                    "SELECT c.relname, pg_get_userbyid(a.grantee), a.privilege_type "
                    "FROM pg_class c, aclexplode(c.relacl) a "
                    "WHERE c.relname IN ('user_identities', 'identity_events', "
                    "'membership_events') AND a.grantee <> c.relowner"
                )
            ).all()
        )
        function_acl = set(
            conn.execute(
                text(
                    "SELECT p.proname, pg_get_userbyid(a.grantee), a.privilege_type "
                    "FROM pg_proc p, aclexplode(p.proacl) a "
                    "WHERE p.pronamespace = 'public'::regnamespace "
                    "AND p.proname LIKE 'heroos_%' AND a.grantee <> p.proowner"
                )
            ).all()
        )
    assert table_acl == {
        ("user_identities", "heroos_app_runtime", "SELECT"),
        ("user_identities", "heroos_identity_operator", "SELECT"),
        ("user_identities", "heroos_identity_operator", "INSERT"),
    }
    # heroos_current_company_id() keeps PostgreSQL's default PUBLIC EXECUTE
    # (it reads a setting only); every new function is restricted.
    assert function_acl == {
        ("heroos_schema_contract", "heroos_app_runtime", "EXECUTE"),
        ("heroos_schema_contract", "heroos_identity_operator", "EXECUTE"),
    }


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
def test_supabase_api_roles_hold_nothing_if_present(admin_engine: Engine, role: str) -> None:
    with admin_engine.connect() as conn:
        if conn.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": role}) == 0:
            pytest.skip(f"{role} does not exist in this cluster (not Supabase)")
        tables = conn.scalars(
            text(
                "SELECT c.relname FROM pg_class c "
                "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') "
                "AND has_table_privilege(:r, c.oid, "
                "'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')"
            ),
            {"r": role},
        ).all()
        functions = conn.scalars(
            text(
                "SELECT p.proname FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace "
                "AND p.proname LIKE 'heroos_%' AND p.proname <> 'heroos_current_company_id' "
                "AND has_function_privilege(:r, p.oid, 'EXECUTE')"
            ),
            {"r": role},
        ).all()
    assert tables == []
    assert functions == []
