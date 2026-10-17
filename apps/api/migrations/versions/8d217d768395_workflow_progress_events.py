"""workflow progress events: append-only record of workflow progression (D3)

M2-03. One table, ``workflow_progress_events``: every progression event of a
workflow instance, written in the same transaction as the decision it records
and under the same instance lock as every other workflow write:

- ``pathway_selected``: the employer's pathway choice (and the one it replaced);
- ``stage_started`` / ``stage_completed``: the employer moved the Case on;
- ``transition_rejected``: a requested transition the rules refused (blocked
  or escalated); the Case did not move;
- ``escalation_recorded``: a transition the rules escalate for specialist
  review, recorded when it first applies (escalations are never released).

Each row holds the decision, its reason codes (engine gate codes and rule keys
with their outcome; never answers, never free text), the warnings the employer
acknowledged, the instance revision, the request's idempotency key, the actor,
the intake status at the time and the rule bundle (id, version, digest) that
decided it. The Case's position is derived from these rows on read: nothing
existing changes and there is no mutable snapshot.

Same contract as D1/D2 (docs/architecture/tenant-isolation.md §9): explicit
``company_id``, Company-qualified foreign keys to the instance and (for an
escalation found by a save) the submission, RLS with the single
``tenant_isolation`` policy, and the API role may only SELECT and INSERT
(append-only: no UPDATE, no DELETE, no cascade from instances). The identity
operator gets nothing. One position change per instance revision and one row
per employer request are unique indexes.

``heroos_schema_contract()`` = 6: the M2-03 API needs this table and refuses to
start on D2; the M2-02 API (contract >= 5) keeps working on D3. Deploy order:
D3, then the API and the operator CLI, then the web app. Downgrade refuses once
any progress event exists: roll forward instead.

Revision ID: 8d217d768395
Revises: e64497d997d8
Create Date: 2026-10-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8d217d768395"
down_revision: str | Sequence[str] | None = "e64497d997d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
POLICY = "tenant_isolation"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
TABLE = "workflow_progress_events"

KINDS = (
    "pathway_selected",
    "stage_started",
    "stage_completed",
    "transition_rejected",
    "escalation_recorded",
)
APPLIED = ("pathway_selected", "stage_started", "stage_completed")
DECISIONS = ("allow", "warn", "block", "escalate")
STATUSES = (
    "case_created",
    "intake_in_progress",
    "awaiting_jurisdiction",
    "screening_not_cleared",
    "screening_unavailable",
    "held_for_specialist_review",
    "intake_recorded",
)
PATHWAYS = ("less_serious", "serious", "undetermined")
# A storage backstop for the reason codes (codes and keys only).
MAX_DETAIL_BYTES = 16384
SHAPE = (
    "(kind = 'pathway_selected' AND pathway IS NOT NULL AND stage IS NULL "
    "AND (decision = 'allow' OR decision = 'warn') AND request_key IS NOT NULL) "
    "OR ((kind = 'stage_started' OR kind = 'stage_completed') AND stage IS NOT NULL "
    "AND previous_pathway IS NULL "
    "AND (decision = 'allow' OR decision = 'warn') AND request_key IS NOT NULL) "
    "OR (kind = 'transition_rejected' AND previous_pathway IS NULL "
    "AND (decision = 'block' OR decision = 'escalate') AND request_key IS NOT NULL) "
    "OR (kind = 'escalation_recorded' AND previous_pathway IS NULL "
    "AND decision = 'escalate' AND request_key IS NULL)"
)


def one_of(column: str, values: tuple[str, ...]) -> str:
    # Written out instead of IN (...): see app.db.models.audit.one_of.
    return " OR ".join(f"{column} = '{value}'" for value in values)


def guard(condition: str, message: str) -> None:
    """Abort the migration transaction if ``condition`` (SQL) is true (fixed message)."""
    op.execute(
        f"DO $guard$ BEGIN IF ({condition}) THEN "
        f"RAISE EXCEPTION 'heroos migration refused: {message}'; "
        "END IF; END $guard$;"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("transition", sa.String(length=100), nullable=False),
        sa.Column("pathway", sa.String(length=30), nullable=True),
        sa.Column("previous_pathway", sa.String(length=30), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("acknowledged", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=True),
        sa.Column("submission_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("bundle_id", sa.String(length=50), nullable=False),
        sa.Column("bundle_version", sa.String(length=50), nullable=False),
        sa.Column("bundle_digest", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("intake_status", sa.String(length=40), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_workflow_progress_events_company_id_companies",
            ondelete="CASCADE",
        ),
        # The instance of the same Company; no cascade (PRIV-020).
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_progress_events_company_id_instance_id",
        ),
        # An escalation found by a save: that submission, of the same instance.
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_workflow_progress_events_submission",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_workflow_progress_events_actor_user_id_users",
        ),
        sa.CheckConstraint(one_of("kind", KINDS), name="ck_workflow_progress_events_kind"),
        sa.CheckConstraint(
            one_of("decision", DECISIONS), name="ck_workflow_progress_events_decision"
        ),
        sa.CheckConstraint(SHAPE, name="ck_workflow_progress_events_shape"),
        sa.CheckConstraint("revision >= 0", name="ck_workflow_progress_events_revision"),
        sa.CheckConstraint(
            "definition_version >= 1", name="ck_workflow_progress_events_definition_version"
        ),
        sa.CheckConstraint(
            f"(pathway IS NULL OR {one_of('pathway', PATHWAYS)}) "
            f"AND (previous_pathway IS NULL OR {one_of('previous_pathway', PATHWAYS)})",
            name="ck_workflow_progress_events_pathway",
        ),
        sa.CheckConstraint(
            "transition ~ '^(pathway|start|complete):[a-z][a-z_]{0,49}$' "
            "AND (stage IS NULL OR stage ~ '^[a-z][a-z_]{0,49}$')",
            name="ck_workflow_progress_events_transition",
        ),
        sa.CheckConstraint(
            "bundle_id ~ '^[a-z][a-z0-9-]{0,49}$' "
            "AND bundle_version ~ '^[a-z0-9][a-z0-9.-]{0,49}$' "
            "AND bundle_digest ~ '^[0-9a-f]{64}$'",
            name="ck_workflow_progress_events_bundle",
        ),
        sa.CheckConstraint(
            one_of("intake_status", STATUSES), name="ck_workflow_progress_events_intake_status"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reasons) = 'array' AND jsonb_typeof(acknowledged) = 'array' "
            f"AND octet_length(reasons::text) + octet_length(acknowledged::text) <= "
            f"{MAX_DETAIL_BYTES}",
            name="ck_workflow_progress_events_detail",
        ),
    )
    op.create_index("ix_workflow_progress_events_instance_id", TABLE, ["instance_id"])
    op.create_index(
        "uq_workflow_progress_events_instance_id_request_key",
        TABLE,
        ["instance_id", "request_key"],
        unique=True,
        postgresql_where=sa.text("request_key IS NOT NULL"),
    )
    op.create_index(
        "uq_workflow_progress_events_instance_id_revision",
        TABLE,
        ["instance_id", "revision"],
        unique=True,
        postgresql_where=sa.text(one_of("kind", APPLIED)),
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON {TABLE}
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING (company_id = heroos_current_company_id())
            WITH CHECK (company_id = heroos_current_company_id())
        """
    )

    _settle_privileges()
    _grant()
    _set_schema_contract(6)


def _settle_privileges() -> None:
    """Remove whatever default privileges attached to the new table (none intended)."""
    op.execute(
        f"""
        DO $$
        DECLARE
            entry record;
        BEGIN
            FOR entry IN
                SELECT DISTINCT a.grantee
                FROM pg_class c, aclexplode(c.relacl) a
                WHERE c.oid = 'public.{TABLE}'::regclass AND a.grantee <> c.relowner
            LOOP
                IF entry.grantee = 0 THEN
                    EXECUTE 'REVOKE ALL ON TABLE public.{TABLE} FROM PUBLIC';
                ELSE
                    EXECUTE format('REVOKE ALL ON TABLE public.{TABLE} FROM %I',
                                   pg_get_userbyid(entry.grantee));
                END IF;
            END LOOP;
        END
        $$;
        """
    )


def _grant() -> None:
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {RUNTIME_ROLE}")

    runtime = f"(SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')"
    guard(
        f"""EXISTS (
            SELECT FROM pg_class c, aclexplode(c.relacl) a
            WHERE c.oid = 'public.{TABLE}'::regclass AND a.grantee <> c.relowner
              AND NOT (a.grantee = {runtime} AND a.privilege_type IN ('SELECT', 'INSERT')))
        OR has_table_privilege('{RUNTIME_ROLE}', 'public.{TABLE}',
                               'UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')
        OR has_any_column_privilege('{RUNTIME_ROLE}', 'public.{TABLE}', 'UPDATE')
        OR has_any_column_privilege('{OPERATOR_ROLE}', 'public.{TABLE}',
                                    'SELECT, INSERT, UPDATE')""",
        "unexpected privileges on workflow_progress_events",
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
    op.execute(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
    guard(
        f"EXISTS (SELECT FROM {TABLE})",
        "workflow progress events exist; a rollback would delete them, so roll forward "
        "instead (deletion is decided by PRIV-020)",
    )
    _set_schema_contract(5)
    op.drop_index("uq_workflow_progress_events_instance_id_revision", table_name=TABLE)
    op.drop_index("uq_workflow_progress_events_instance_id_request_key", table_name=TABLE)
    op.drop_index("ix_workflow_progress_events_instance_id", table_name=TABLE)
    op.drop_table(TABLE)
