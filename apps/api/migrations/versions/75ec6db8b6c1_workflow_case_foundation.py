"""workflow case foundation: instances, submissions and versioned facts (D1)

M2-01. The first M2 workflow entities, following the tenant-isolation contract
for future private entities (docs/architecture/tenant-isolation.md §9):

- ``workflow_instances``: one guided workflow attached to a Case (one per Case
  for now). Records the workflow and definition version the Case runs, an
  optimistic-concurrency ``revision`` (bumped by every saved answer group), the
  client's ``request_key`` (idempotent Case creation) and the creating User.
- ``workflow_submissions``: one saved answer group (a step's answers saved at
  once): the revision it produced, its idempotency key and the submitting User.
- ``case_facts``: the answers themselves, versioned and append-only. A fact is
  never updated: a later submission records a new value (``NULL`` = cleared).
  Facts are stored independently of how a conversation presents them.

Every table has an explicit ``company_id``, Company-qualified foreign keys
(``(company_id, case_id)``, ``(company_id, instance_id)``,
``(company_id, instance_id, submission_id)``), RLS with the single
``tenant_isolation`` policy, and least-privilege grants for the API role:

- ``workflow_instances``: SELECT, INSERT, UPDATE of ``revision`` and
  ``updated_at`` only;
- ``workflow_submissions``, ``case_facts``: SELECT and INSERT (append-only).

No DELETE anywhere, and no cascade from Cases: deletion behaviour is a privacy
decision (PRIV-020), not a technical default. A Case that has a workflow cannot
be deleted (the foreign key refuses). The identity operator gets nothing.

``heroos_schema_contract()`` = 4, so an API that needs these tables refuses to
start on an older schema. Downgrade refuses once any workflow data exists:
roll forward instead.

Revision ID: 75ec6db8b6c1
Revises: 3f6c2a9d81b4
Create Date: 2026-10-15 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "75ec6db8b6c1"
down_revision: str | Sequence[str] | None = "3f6c2a9d81b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
POLICY = "tenant_isolation"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
NEW_TABLES = ("workflow_instances", "workflow_submissions", "case_facts")
# Known workflow keys; a new workflow (M3) adds its key here and in app.workflows.
WORKFLOW_KEYS = ("disciplinary",)
# Facts are small structured answers; free text is limited by the API (4,000
# characters). This is a storage backstop, not the product limit.
MAX_FACT_VALUE_BYTES = 16384


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true (fixed message)."""
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    """Upgrade schema."""
    keys = ", ".join(f"'{key}'" for key in WORKFLOW_KEYS)
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("workflow_key", sa.String(length=50), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_workflow_instances_company_id_companies",
            ondelete="CASCADE",
        ),
        # Same-Company reference; no cascade from Cases (PRIV-020).
        sa.ForeignKeyConstraint(
            ["company_id", "case_id"],
            ["cases.company_id", "cases.id"],
            name="fk_workflow_instances_company_id_case_id_cases",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_workflow_instances_created_by_user_id_users",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_workflow_instances_company_id_id"),
        sa.UniqueConstraint(
            "company_id", "case_id", name="uq_workflow_instances_company_id_case_id"
        ),
        sa.UniqueConstraint(
            "company_id", "request_key", name="uq_workflow_instances_company_id_request_key"
        ),
        sa.CheckConstraint(f"workflow_key IN ({keys})", name="ck_workflow_instances_workflow_key"),
        sa.CheckConstraint(
            "definition_version >= 1", name="ck_workflow_instances_definition_version"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_workflow_instances_revision"),
    )
    op.create_index(
        "ix_workflow_instances_company_id_workflow_key",
        "workflow_instances",
        ["company_id", "workflow_key"],
    )

    op.create_table(
        "workflow_submissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.String(length=50), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_workflow_submissions_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_submissions_company_id_instance_id",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            name="fk_workflow_submissions_submitted_by_user_id_users",
        ),
        # Target of the case_facts composite key (a fact's submission belongs to
        # the same Company and the same instance).
        sa.UniqueConstraint(
            "company_id",
            "instance_id",
            "id",
            name="uq_workflow_submissions_company_id_instance_id_id",
        ),
        sa.UniqueConstraint(
            "instance_id", "revision", name="uq_workflow_submissions_instance_id_revision"
        ),
        sa.UniqueConstraint(
            "instance_id",
            "idempotency_key",
            name="uq_workflow_submissions_instance_id_idempotency_key",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_workflow_submissions_revision"),
        sa.CheckConstraint(
            "char_length(step_key) BETWEEN 1 AND 50", name="ck_workflow_submissions_step_key"
        ),
    )

    op.create_table(
        "case_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("fact_key", sa.String(length=100), nullable=False),
        # NULL: the answer was cleared by this submission.
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_case_facts_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_case_facts_company_id_instance_id_submission_id",
        ),
        sa.UniqueConstraint(
            "submission_id", "fact_key", name="uq_case_facts_submission_id_fact_key"
        ),
        sa.CheckConstraint(
            "char_length(fact_key) BETWEEN 1 AND 100", name="ck_case_facts_fact_key"
        ),
        sa.CheckConstraint(
            f"value IS NULL OR octet_length(value::text) <= {MAX_FACT_VALUE_BYTES}",
            name="ck_case_facts_value_size",
        ),
    )
    op.create_index("ix_case_facts_instance_id_fact_key", "case_facts", ["instance_id", "fact_key"])

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {POLICY} ON {table}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (company_id = heroos_current_company_id())
                WITH CHECK (company_id = heroos_current_company_id())
            """
        )

    _settle_privileges()
    _grant()
    _set_schema_contract(4)


def _settle_privileges() -> None:
    """Remove whatever default privileges attached to the new tables (none intended).

    Default privileges (e.g. Supabase's grants to ``anon``, ``authenticated``
    and ``service_role``) can attach to every table this migration creates.
    Portable: nothing assumes those roles exist.
    """
    oids = ", ".join(f"'public.{table}'::regclass" for table in NEW_TABLES)
    op.execute(
        f"""
        DO $$
        DECLARE
            entry record;
        BEGIN
            FOR entry IN
                SELECT DISTINCT c.oid::regclass::text AS target, a.grantee
                FROM pg_class c, aclexplode(c.relacl) a
                WHERE c.oid IN ({oids}) AND a.grantee <> c.relowner
            LOOP
                IF entry.grantee = 0 THEN
                    EXECUTE format('REVOKE ALL ON TABLE %s FROM PUBLIC', entry.target);
                ELSE
                    EXECUTE format('REVOKE ALL ON TABLE %s FROM %I',
                                   entry.target, pg_get_userbyid(entry.grantee));
                END IF;
            END LOOP;
        END
        $$;
        """
    )


def _grant() -> None:
    op.execute(f"GRANT SELECT, INSERT ON workflow_instances TO {RUNTIME_ROLE}")
    op.execute(f"GRANT UPDATE (revision, updated_at) ON workflow_instances TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON workflow_submissions TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON case_facts TO {RUNTIME_ROLE}")

    oids = ", ".join(f"'public.{table}'::regclass" for table in NEW_TABLES)
    runtime = f"(SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')"
    guard(
        f"""EXISTS (
            SELECT FROM pg_class c, aclexplode(c.relacl) a
            WHERE c.oid IN ({oids}) AND a.grantee <> c.relowner
              AND NOT (a.grantee = {runtime} AND a.privilege_type IN ('SELECT', 'INSERT')))
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.workflow_instances',
                               'UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.workflow_submissions',
                               'UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.case_facts',
                               'UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')""",
        "unexpected privileges on the workflow tables",
    )
    roles = ", ".join(f"'{role}'" for role in SUPABASE_API_ROLES)
    guard(
        f"""EXISTS (
            SELECT FROM pg_roles r, pg_class c
            WHERE r.rolname IN ({roles})
              AND c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
              AND has_table_privilege(r.oid, c.oid,
                    'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'))""",
        "anon, authenticated or service_role hold privileges on a HeroOS table; revoke "
        "them (and their default privileges) before migrating",
    )


def _set_schema_contract(value: int) -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION public.heroos_schema_contract() RETURNS integer "
        f"LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT {value} $$"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "LOCK TABLE workflow_instances, workflow_submissions, case_facts IN ACCESS EXCLUSIVE MODE"
    )
    guard(
        "EXISTS (SELECT FROM workflow_instances) OR EXISTS (SELECT FROM workflow_submissions) "
        "OR EXISTS (SELECT FROM case_facts)",
        "workflow cases or answers exist; a rollback would delete them, so roll forward "
        "instead (deletion is decided by PRIV-020)",
    )
    _set_schema_contract(3)
    op.drop_index("ix_case_facts_instance_id_fact_key", table_name="case_facts")
    op.drop_table("case_facts")
    op.drop_table("workflow_submissions")
    op.drop_index("ix_workflow_instances_company_id_workflow_key", table_name="workflow_instances")
    op.drop_table("workflow_instances")
