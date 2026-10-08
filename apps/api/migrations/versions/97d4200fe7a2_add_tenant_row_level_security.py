"""add tenant row level security

Enables PostgreSQL Row-Level Security on every tenant-owned table and grants the
API runtime role only the DML it needs. See docs/architecture/tenant-isolation.md.

- ``heroos_app_runtime`` is a NOLOGIN privilege role: no password, never
  superuser, never BYPASSRLS, owns nothing. Login roles that the API connects as
  are made members of it outside migrations (local bootstrap script / deployment
  configuration), so no credential ever appears here.
- ``heroos_current_company_id()`` reads the transaction-local
  ``heroos.company_id`` setting. Unset or empty yields NULL, which matches no row.
- Each tenant table gets exactly one permissive ``FOR ALL`` policy with identical
  USING and WITH CHECK expressions, so rows outside the current Company can be
  neither seen, changed, deleted nor created. There is no second policy that could
  be OR-ed in.
- ``users`` is a global identity table (no company_id) and gets no tenant policy;
  the runtime role may only SELECT it.

Downgrade removes policies, RLS, grants and the helper function. The role itself
is cluster-wide (shared by every database on the server) and is left in place.

Revision ID: 97d4200fe7a2
Revises: 27172384eed3
Create Date: 2026-10-08 14:45:16.851632

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "97d4200fe7a2"
down_revision: str | Sequence[str] | None = "27172384eed3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
POLICY = "tenant_isolation"

# Tenant-owned table -> column holding the owning Company's id.
TENANT_TABLES = {
    "companies": "id",
    "memberships": "company_id",
    "company_blueprints": "company_id",
    "case_subjects": "company_id",
    "cases": "company_id",
}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
                CREATE ROLE {RUNTIME_ROLE}
                    NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
            -- A pre-existing role must not be able to bypass RLS.
            IF EXISTS (
                SELECT FROM pg_roles
                WHERE rolname = '{RUNTIME_ROLE}'
                  AND (rolsuper OR rolbypassrls OR rolcreaterole)
            ) THEN
                RAISE EXCEPTION 'role % must not be SUPERUSER, BYPASSRLS or CREATEROLE',
                    '{RUNTIME_ROLE}';
            END IF;
        END
        $$;
        """
    )

    # SECURITY INVOKER (the default): grants nothing, only reads a setting.
    op.execute(
        """
        CREATE FUNCTION heroos_current_company_id() RETURNS uuid
            LANGUAGE sql STABLE PARALLEL SAFE
            AS $$ SELECT NULLIF(pg_catalog.current_setting('heroos.company_id', true), '')::uuid $$;
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT ON users TO {RUNTIME_ROLE}")

    for table, column in TENANT_TABLES.items():
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {RUNTIME_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {POLICY} ON {table}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING ({column} = heroos_current_company_id())
                WITH CHECK ({column} = heroos_current_company_id())
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM {RUNTIME_ROLE}")

    op.execute(f"REVOKE ALL ON users FROM {RUNTIME_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RUNTIME_ROLE}")
    op.execute("DROP FUNCTION heroos_current_company_id()")
