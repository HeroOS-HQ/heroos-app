"""workflow decision records: append-only employer decisions and observations (D4)

M2-04. One table, ``workflow_decision_records``: what a Company administrator
records about the employer's own handling of a Case (an internal review
completed, information requested, a meeting held, an observation, a pause or
follow-up, another factual note), with the date the employer gives, who the
employer says is responsible, an explanation, and references to supporting
evidence the employer holds. HeroOS stores the references only (no files, no
links it would open) and verifies none of it.

A record is the employer's account, never a workflow authorization: the
categories are factual only (no warning, suspension, penalty, dismissal,
finding or specialist approval exists in the vocabulary, so the database
refuses them), and nothing here moves a stage or releases a hold.

Corrections never overwrite: a correction or clarification is a new row that
supersedes exactly one earlier row. A Company-qualified foreign key keeps the
superseded row in the same chain, Case and Company; a unique ``supersedes_id``
lets a row be superseded at most once (each chain is a single line, and a new
row can only point at an existing one, so a cycle can't be formed). Every row
records the instance revision it produced (one per revision), its request key
(one row per request), the authenticated actor and the workflow context.

Same contract as D1 to D3 (docs/architecture/tenant-isolation.md §9): explicit
``company_id``, Company-qualified foreign keys, RLS with the single
``tenant_isolation`` policy, and the API role may only SELECT and INSERT
(append-only: no UPDATE, no DELETE, no cascade from instances). The identity
operator gets nothing.

``heroos_schema_contract()`` = 7: the M2-04 API needs this table and refuses to
start on D3; the M2-03 API (contract >= 6) keeps working on D4. Deploy order:
D4, then the API and the operator CLI, then the web app. Downgrade refuses once
any decision record exists: roll forward instead.

Revision ID: c4a7e2d9b310
Revises: 8d217d768395
Create Date: 2026-10-18 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4a7e2d9b310"
down_revision: str | Sequence[str] | None = "8d217d768395"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
POLICY = "tenant_isolation"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
TABLE = "workflow_decision_records"

CATEGORIES = (
    "internal_review_completed",
    "information_requested",
    "meeting_recorded",
    "employer_observation",
    "internal_pause_or_follow_up",
    "other_note",
)
RELATIONS = ("original", "correction", "clarification")
DECISION_MAKERS = ("recorder", "other")
EVIDENCE_STATUSES = ("held", "none", "not_sure")
INTAKE_STATUSES = (
    "case_created",
    "intake_in_progress",
    "awaiting_jurisdiction",
    "screening_not_cleared",
    "screening_unavailable",
    "held_for_specialist_review",
    "intake_recorded",
)
PROGRESSION_STATUSES = (
    "unavailable",
    "incompatible",
    "held",
    "paused",
    "intake_incomplete",
    "not_covered",
    "awaiting_pathway",
    "undetermined",
    "pathway_not_covered",
    "ready",
    "in_stage",
    "no_further_stage",
    "closed",
)
MAX_SUMMARY = 200
MAX_EXPLANATION = 4000
MAX_ROLE = 120
MAX_CHANGE_REASON = 500
MAX_EVIDENCE_ITEMS = 10
# A storage backstop for the evidence references, not a product rule.
MAX_EVIDENCE_BYTES = 8192
SHAPE = (
    "(relation = 'original' AND supersedes_id IS NULL AND chain_id = id "
    "AND change_reason IS NULL) "
    "OR ((relation = 'correction' OR relation = 'clarification') "
    "AND supersedes_id IS NOT NULL AND supersedes_id <> id AND chain_id <> id "
    "AND change_reason IS NOT NULL)"
)
DECISION_MAKER_SHAPE = (
    "(decision_maker = 'recorder' AND decision_maker_role IS NULL) "
    "OR (decision_maker = 'other' AND decision_maker_role IS NOT NULL)"
)
# Single-line text: no control character at all. Multi-line text: line breaks
# and tabs only. The class is built with chr(): no backslash, and no "[:name:]"
# (SQLAlchemy would read ":name" as a bind parameter).
CONTROL = "('[' || chr(1) || '-' || chr(31) || chr(127) || '-' || chr(159) || ']')"
SINGLE_LINE = "{column} !~ " + CONTROL
MULTI_LINE = "translate({column}, chr(9) || chr(10), '') !~ " + CONTROL
# Lengths as two comparisons, never BETWEEN: PostgreSQL keeps BETWEEN as a
# nested AND, which a dump and restore flattens, so the restored constraint
# would read differently (the backup/restore gate compares the catalogs exactly).
LENGTH = "char_length({column}) >= 1 AND char_length({column}) <= {maximum}"
TEXT = (
    f"{LENGTH.format(column='summary', maximum=MAX_SUMMARY)} "
    f"AND {SINGLE_LINE.format(column='summary')} "
    f"AND {LENGTH.format(column='explanation', maximum=MAX_EXPLANATION)} "
    f"AND {MULTI_LINE.format(column='explanation')} "
    "AND (decision_maker_role IS NULL OR "
    f"({LENGTH.format(column='decision_maker_role', maximum=MAX_ROLE)} "
    f"AND {SINGLE_LINE.format(column='decision_maker_role')})) "
    "AND (change_reason IS NULL OR "
    f"({LENGTH.format(column='change_reason', maximum=MAX_CHANGE_REASON)} "
    f"AND {MULTI_LINE.format(column='change_reason')}))"
)
# Held evidence is described by at least one reference; otherwise none is listed.
EVIDENCE = (
    "CASE WHEN jsonb_typeof(evidence) = 'array' THEN "
    f"jsonb_array_length(evidence) <= {MAX_EVIDENCE_ITEMS} "
    f"AND octet_length(evidence::text) <= {MAX_EVIDENCE_BYTES} "
    "AND (evidence_status = 'held') = (jsonb_array_length(evidence) > 0) "
    "ELSE false END"
)
# A guard against typos (the API allows one day ahead for time zones east of UTC).
OCCURRED_ON = (
    "occurred_on >= DATE '1990-01-01' "
    "AND occurred_on <= CAST(timezone('UTC', recorded_at) AS date) + 1"
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
        sa.Column("chain_id", sa.UUID(), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=MAX_SUMMARY), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("decision_maker", sa.String(length=20), nullable=False),
        sa.Column("decision_maker_role", sa.String(length=MAX_ROLE), nullable=True),
        sa.Column("evidence_status", sa.String(length=20), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_reason", sa.String(length=MAX_CHANGE_REASON), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.UUID(), nullable=False),
        sa.Column("recorded_by_user_id", sa.UUID(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("intake_status", sa.String(length=40), nullable=False),
        sa.Column("progression_status", sa.String(length=30), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_workflow_decision_records_company_id_companies",
            ondelete="CASCADE",
        ),
        # The instance of the same Company; no cascade (PRIV-020).
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_decision_records_company_id_instance_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "instance_id",
            "chain_id",
            "id",
            name="uq_workflow_decision_records_chain_member",
        ),
        # A correction targets a record of the same chain, Case and Company.
        sa.ForeignKeyConstraint(
            ["company_id", "instance_id", "chain_id", "supersedes_id"],
            [
                f"{TABLE}.company_id",
                f"{TABLE}.instance_id",
                f"{TABLE}.chain_id",
                f"{TABLE}.id",
            ],
            name="fk_workflow_decision_records_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["users.id"],
            name="fk_workflow_decision_records_recorded_by_user_id_users",
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_workflow_decision_records_supersedes_id"),
        sa.UniqueConstraint(
            "instance_id",
            "request_key",
            name="uq_workflow_decision_records_instance_id_request_key",
        ),
        sa.UniqueConstraint(
            "instance_id", "revision", name="uq_workflow_decision_records_instance_id_revision"
        ),
        sa.CheckConstraint(
            one_of("category", CATEGORIES), name="ck_workflow_decision_records_category"
        ),
        sa.CheckConstraint(
            one_of("relation", RELATIONS), name="ck_workflow_decision_records_relation"
        ),
        sa.CheckConstraint(SHAPE, name="ck_workflow_decision_records_shape"),
        sa.CheckConstraint(
            f"({one_of('decision_maker', DECISION_MAKERS)}) AND ({DECISION_MAKER_SHAPE})",
            name="ck_workflow_decision_records_decision_maker",
        ),
        sa.CheckConstraint(
            one_of("evidence_status", EVIDENCE_STATUSES),
            name="ck_workflow_decision_records_evidence_status",
        ),
        sa.CheckConstraint(
            one_of("intake_status", INTAKE_STATUSES),
            name="ck_workflow_decision_records_intake_status",
        ),
        sa.CheckConstraint(
            one_of("progression_status", PROGRESSION_STATUSES),
            name="ck_workflow_decision_records_progression_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_workflow_decision_records_revision"),
        sa.CheckConstraint(
            "definition_version >= 1", name="ck_workflow_decision_records_definition_version"
        ),
        sa.CheckConstraint(TEXT, name="ck_workflow_decision_records_text"),
        sa.CheckConstraint(EVIDENCE, name="ck_workflow_decision_records_evidence"),
        sa.CheckConstraint(OCCURRED_ON, name="ck_workflow_decision_records_occurred_on"),
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
    _set_schema_contract(7)


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
        "unexpected privileges on workflow_decision_records",
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
        "workflow decision records exist; a rollback would delete them, so roll forward "
        "instead (deletion is decided by PRIV-020)",
    )
    _set_schema_contract(6)
    op.drop_table(TABLE)
