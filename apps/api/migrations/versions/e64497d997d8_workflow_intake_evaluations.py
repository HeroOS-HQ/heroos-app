"""workflow intake evaluations: append-only trace of each save's evaluation (D2)

M2-02. One table, ``workflow_evaluations``: the intake evaluation that each
saved answer group (``workflow_submissions`` row) produced, written in the same
transaction as the submission:

- the Case status, the hold (``jurisdiction`` = paused until confirmed,
  ``specialist_review`` = escalated) and why (``hold_reason``), the resolved
  Case jurisdiction and the safety-screening state;
- ``results``: every rule's result in rule-set order, with the rule key,
  outcome, action, reason code and the structured answers it read
  (enumerated values only, and for sensitive questions only counts; free text
  is never copied here);
- the definition version and the rule-set version and digest used.

Nothing else changes: the Case jurisdiction confirmation is a ``case_facts``
answer, and the current hold and status are recomputed on every read. Case
history is composed from these rows, the submissions and the instance.

Same contract as D1 (docs/architecture/tenant-isolation.md §9): explicit
``company_id``, a Company-qualified foreign key to the submission
(``(company_id, instance_id, submission_id)``), RLS with the single
``tenant_isolation`` policy, and the API role may only SELECT and INSERT
(append-only: no UPDATE, no DELETE, no cascade from submissions). The identity
operator gets nothing.

``heroos_schema_contract()`` = 5: the M2-02 API needs this table and refuses to
start on D1; the M2-01 API (contract >= 4) keeps working on D2. Deploy order:
D2, then the API and the operator CLI, then the web app. Downgrade refuses once
any evaluation exists: roll forward instead.

Revision ID: e64497d997d8
Revises: 75ec6db8b6c1
Create Date: 2026-10-16 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e64497d997d8"
down_revision: str | Sequence[str] | None = "75ec6db8b6c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
POLICY = "tenant_isolation"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
TABLE = "workflow_evaluations"

STATUSES = (
    "case_created",
    "intake_in_progress",
    "awaiting_jurisdiction",
    "screening_not_cleared",
    "screening_unavailable",
    "held_for_specialist_review",
    "intake_recorded",
)
HOLDS = ("jurisdiction", "specialist_review")
HOLD_REASONS = (
    "high_risk_factors",
    "jurisdiction_different",
    "jurisdiction_unsupported",
    "screening_not_covered",
    "earlier_escalation",
    "company_jurisdiction_unconfirmed",
    "case_jurisdiction_not_sure",
    "case_jurisdiction_outdated",
)
JURISDICTIONS = ("uae_federal", "difc")
SCREENING = (
    "not_applicable",
    "disabled",
    "not_started",
    "incomplete",
    "not_cleared",
    "cleared",
    "positive",
)
# A storage backstop for the trace (codes and enumerated answers only).
MAX_RESULTS_BYTES = 65536


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
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=50), nullable=False),
        sa.Column("ruleset_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("hold", sa.String(length=30), nullable=True),
        sa.Column("hold_reason", sa.String(length=40), nullable=True),
        sa.Column("jurisdiction", sa.String(length=20), nullable=True),
        sa.Column("screening", sa.String(length=20), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_workflow_evaluations_company_id_companies",
            ondelete="CASCADE",
        ),
        # The submission of the same Company and instance; no cascade (PRIV-020).
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_workflow_evaluations_company_id_instance_id_submission_id",
        ),
        # One evaluation per saved submission.
        sa.UniqueConstraint("submission_id", name="uq_workflow_evaluations_submission_id"),
        sa.CheckConstraint(
            "definition_version >= 1", name="ck_workflow_evaluations_definition_version"
        ),
        sa.CheckConstraint(
            "ruleset_version ~ '^[a-z0-9][a-z0-9.-]{0,49}$'",
            name="ck_workflow_evaluations_ruleset_version",
        ),
        sa.CheckConstraint(
            "ruleset_digest ~ '^[0-9a-f]{64}$'", name="ck_workflow_evaluations_ruleset_digest"
        ),
        sa.CheckConstraint(one_of("status", STATUSES), name="ck_workflow_evaluations_status"),
        sa.CheckConstraint(
            "(hold IS NULL AND hold_reason IS NULL) OR (hold IS NOT NULL AND hold_reason IS NOT "
            f"NULL AND ({one_of('hold', HOLDS)}) AND ({one_of('hold_reason', HOLD_REASONS)}))",
            name="ck_workflow_evaluations_hold",
        ),
        sa.CheckConstraint(
            f"jurisdiction IS NULL OR {one_of('jurisdiction', JURISDICTIONS)}",
            name="ck_workflow_evaluations_jurisdiction",
        ),
        sa.CheckConstraint(
            one_of("screening", SCREENING), name="ck_workflow_evaluations_screening"
        ),
        sa.CheckConstraint(
            f"jsonb_typeof(results) = 'array' AND octet_length(results::text) <= "
            f"{MAX_RESULTS_BYTES}",
            name="ck_workflow_evaluations_results",
        ),
    )
    op.create_index("ix_workflow_evaluations_instance_id", TABLE, ["instance_id"])

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
    _set_schema_contract(5)


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
        "unexpected privileges on workflow_evaluations",
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
        "intake evaluations exist; a rollback would delete them, so roll forward instead "
        "(deletion is decided by PRIV-020)",
    )
    _set_schema_contract(4)
    op.drop_index("ix_workflow_evaluations_instance_id", table_name=TABLE)
    op.drop_table(TABLE)
