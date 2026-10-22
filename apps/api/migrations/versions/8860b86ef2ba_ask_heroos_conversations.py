"""ask heroos conversations: durable conversations, turns, messages and evaluations (D6)

M2-NEW-07. Ask HeroOS conversations become durable, Company-owned records
around the existing Case chain (Case -> WorkflowInstance -> WorkflowSubmission
-> CaseFact); nothing here is a second Case system.

- ``assistant_conversations``: one Ask HeroOS conversation. Created by the
  first turn that completes with a visible HeroOS reply (never by opening an
  empty one). At most one Case (``case_id``, set once; a Case has at most one
  conversation), the established workflow, a safe title, an optimistic-
  concurrency ``revision`` and a bounded ``checkpoint`` (the trusted state the
  next turn starts from; rebuildable from the records below and the Case).
- ``assistant_turns``: one founder message and HeroOS's reply, in order, with
  the client's ``turn_key``: unique per Company, so a retried first turn (which
  has no conversation yet) replays instead of creating a second conversation.
- ``assistant_messages``: what a person saw. A founder message (its words and
  author) or HeroOS's visible reply (its safe next step, how the turn was
  handled and the outcome card). Never a provider payload, prompt, repair or
  reasoning, and no knowledge text.
- ``assistant_turn_evaluations``: the deterministic evaluation of the turn
  (M2-NEW-06 ``ConversationEvaluation.record()``, bounded) with small
  queryable columns (matter, workflow, availability, presentation, outcome,
  review requirement, snapshot and profile identity) and the decisions the
  founder explicitly withdrew in that turn (``withdrawn_actions``: with the
  records, what rebuilds which reviews are active). Separate from
  ``workflow_evaluations`` (the structured intake trace of a submission).

Access paths, each index-backed: a Company's conversations by recent activity
(``company_id, updated_at, id``: keyset pages); a conversation's messages and
turns by sequence; a turn key per Company (idempotency); a conversation's Case
(its row) and a Case's conversation (``company_id, case_id``); a turn's
evaluation and messages. No index reads HR text or the evaluation JSON.
- ``workflow_submissions`` gains ``origin`` (``structured`` for every existing
  and form-saved row; ``assistant`` for canonical facts an Ask HeroOS turn
  established) and ``source_message_id``, the founder message an assistant
  submission came from (a Company-qualified reference, never a copy).

Same contract as D1 to D5 (docs/architecture/tenant-isolation.md §9): explicit
``company_id``, Company-qualified foreign keys, RLS with the single
``tenant_isolation`` policy. The API role may only SELECT and INSERT turns,
messages and evaluations (append-only); on a conversation it may also UPDATE
the revision, Case attachment, workflow, title, checkpoint and activity time
(column-level). Nothing cascades from Cases, conversations, turns or messages
(PRIV-020); there is no DELETE grant. The identity operator gets nothing.

``heroos_schema_contract()`` = 9: the M2-NEW-07 API needs these tables and
refuses to start on D5; the M2-NEW-06 API (contract >= 8) keeps working on D6
(it never names the new tables, and new submissions default to
``structured``). Deploy order: D6, then the API and the operator CLI, then
the web app. Downgrade refuses once any conversation or assistant submission
exists: roll forward instead.

Revision ID: 8860b86ef2ba
Revises: 671bbbfc74ae
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8860b86ef2ba"
down_revision: str | Sequence[str] | None = "671bbbfc74ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "heroos_app_runtime"
OPERATOR_ROLE = "heroos_identity_operator"
POLICY = "tenant_isolation"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")
CONVERSATIONS = "assistant_conversations"
TURNS = "assistant_turns"
MESSAGES = "assistant_messages"
EVALUATIONS = "assistant_turn_evaluations"
NEW_TABLES = (CONVERSATIONS, TURNS, MESSAGES, EVALUATIONS)
APPEND_ONLY = (TURNS, MESSAGES, EVALUATIONS)
# The only conversation columns the API role may change.
CONVERSATION_UPDATES = ("case_id", "workflow_key", "title", "revision", "checkpoint", "updated_at")

WORKFLOW_KEYS = ("disciplinary",)
MESSAGE_ROLES = ("founder", "heroos")
CONVERSATION_STATES = ("responded", "clarifying", "outside_approved_guidance")
OUTCOME_KINDS = ("guidance", "warning", "block", "expert_review", "unavailable")
PRESENTATIONS = ("guidance", "warning", "block", "expert_review")
MATTERS = (
    "supported", "unsupported_hr", "outside_product_scope", "unclear", "confidential_request",
)  # fmt: skip
AVAILABILITIES = (
    "ready", "knowledge_bundle_missing", "rule_bundle_missing", "execution_profile_missing",
    "incompatible_versions", "unsupported_executor", "privacy_capability_unavailable",
    "invalid_continuation", "internal_failure",
)  # fmt: skip
SUBMISSION_ORIGINS = ("structured", "assistant")
ASSISTANT_STEP_KEY = "ask_heroos"
# Bounds on storage, not product rules (app.db.models.assistant).
MAX_TURNS = 10000
MAX_TITLE = 120
MAX_FOUNDER_CHARS = 2000
MAX_HEROOS_CHARS = 8000
MAX_NEXT_STEP_CHARS = 1000
MAX_OUTCOME_BYTES = 8192
MAX_CHECKPOINT_BYTES = 8192
MAX_EVALUATION_BYTES = 65536
MAX_WITHDRAWN = 3

# Single-line text: no control character at all. Multi-line text: line breaks,
# carriage returns and tabs only (what the founder may send). The classes are
# built with chr(): no backslash, and no "[:name:]" (SQLAlchemy would read
# ":name" as a bind parameter).
CONTROL = "('[' || chr(1) || '-' || chr(31) || chr(127) || '-' || chr(159) || ']')"
SINGLE_LINE = "{column} !~ " + CONTROL
MULTI_LINE = "translate({column}, chr(9) || chr(10) || chr(13), '') !~ " + CONTROL
# Lengths as two comparisons, never BETWEEN: a dump and restore flattens it,
# and the backup/restore gate compares the catalogs exactly.
LENGTH = "char_length({column}) >= 1 AND char_length({column}) <= {maximum}"
TITLE = (
    f"title IS NULL OR ({LENGTH.format(column='title', maximum=MAX_TITLE)} "
    f"AND {SINGLE_LINE.format(column='title')})"
)
CHECKPOINT = (
    "jsonb_typeof(checkpoint) = 'object' "
    f"AND octet_length(checkpoint::text) <= {MAX_CHECKPOINT_BYTES}"
)
CONVERSATION_SHAPE = "case_id IS NULL OR workflow_key IS NOT NULL"
MESSAGE_SHAPE = (
    "(role = 'founder' AND actor_user_id IS NOT NULL AND safe_next_step IS NULL "
    "AND conversation_state IS NULL AND outcome IS NULL) "
    "OR (role = 'heroos' AND actor_user_id IS NULL AND conversation_state IS NOT NULL)"
)
MESSAGE_TEXT = (
    f"((role = 'founder' AND {LENGTH.format(column='content', maximum=MAX_FOUNDER_CHARS)}) "
    f"OR (role = 'heroos' AND {LENGTH.format(column='content', maximum=MAX_HEROOS_CHARS)})) "
    f"AND {MULTI_LINE.format(column='content')} "
    "AND (safe_next_step IS NULL OR "
    f"({LENGTH.format(column='safe_next_step', maximum=MAX_NEXT_STEP_CHARS)} "
    f"AND {MULTI_LINE.format(column='safe_next_step')}))"
)
MESSAGE_OUTCOME = (
    "outcome IS NULL OR (jsonb_typeof(outcome) = 'object' "
    f"AND octet_length(outcome::text) <= {MAX_OUTCOME_BYTES})"
)
EVALUATION_IDENTITY = (
    "char_length(evaluation_schema) >= 1 AND char_length(snapshot_id) >= 1 "
    "AND (workflow_key IS NULL OR char_length(workflow_key) >= 1) "
    "AND (knowledge_runtime_digest IS NULL OR char_length(knowledge_runtime_digest) = 64) "
    "AND (profile_digest IS NULL OR char_length(profile_digest) = 64)"
)
EVALUATION_RECORD = (
    f"jsonb_typeof(record) = 'object' AND octet_length(record::text) <= {MAX_EVALUATION_BYTES}"
)
WITHDRAWN = (
    "jsonb_typeof(withdrawn_actions) = 'array' "
    f"AND jsonb_array_length(withdrawn_actions) <= {MAX_WITHDRAWN}"
)
SUBMISSION_ORIGIN = (
    "(origin = 'structured' OR origin = 'assistant') AND ("
    "(origin = 'structured' AND source_message_id IS NULL) "
    "OR (origin = 'assistant' AND source_message_id IS NOT NULL "
    f"AND step_key = '{ASSISTANT_STEP_KEY}'))"
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


def _company_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["company_id"],
        ["companies.id"],
        name=f"fk_{table}_company_id_companies",
        ondelete="CASCADE",
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        CONVERSATIONS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.Column("workflow_key", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=MAX_TITLE), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        _company_fk(CONVERSATIONS),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_assistant_conversations_created_by_user_id_users",
        ),
        # The Case of the same Company; no cascade (PRIV-020).
        sa.ForeignKeyConstraint(
            ["company_id", "case_id"],
            ["cases.company_id", "cases.id"],
            name="fk_assistant_conversations_company_id_case_id_cases",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_assistant_conversations_company_id_id"),
        sa.UniqueConstraint(
            "company_id", "case_id", name="uq_assistant_conversations_company_id_case_id"
        ),
        sa.CheckConstraint(
            f"workflow_key IS NULL OR {one_of('workflow_key', WORKFLOW_KEYS)}",
            name="ck_assistant_conversations_workflow_key",
        ),
        sa.CheckConstraint(CONVERSATION_SHAPE, name="ck_assistant_conversations_case_workflow"),
        sa.CheckConstraint(
            f"revision >= 0 AND revision <= {MAX_TURNS}", name="ck_assistant_conversations_revision"
        ),
        sa.CheckConstraint(TITLE, name="ck_assistant_conversations_title"),
        sa.CheckConstraint(CHECKPOINT, name="ck_assistant_conversations_checkpoint"),
    )
    # The Company's conversations, most recent first (keyset pages on updated_at, id).
    op.create_index(
        "ix_assistant_conversations_company_id_updated_at",
        CONVERSATIONS,
        ["company_id", "updated_at", "id"],
    )

    op.create_table(
        TURNS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("turn_key", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        _company_fk(TURNS),
        sa.ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            [f"{CONVERSATIONS}.company_id", f"{CONVERSATIONS}.id"],
            name="fk_assistant_turns_company_id_conversation_id",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_assistant_turns_actor_user_id_users"
        ),
        sa.UniqueConstraint(
            "company_id",
            "conversation_id",
            "id",
            name="uq_assistant_turns_company_id_conversation_id_id",
        ),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_assistant_turns_conversation_id_sequence"
        ),
        sa.UniqueConstraint(
            "company_id", "turn_key", name="uq_assistant_turns_company_id_turn_key"
        ),
        sa.CheckConstraint(
            f"sequence >= 1 AND sequence <= {MAX_TURNS}", name="ck_assistant_turns_sequence"
        ),
    )

    op.create_table(
        MESSAGES,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("safe_next_step", sa.Text(), nullable=True),
        sa.Column("conversation_state", sa.String(length=30), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        _company_fk(MESSAGES),
        # The turn of the same conversation and Company.
        sa.ForeignKeyConstraint(
            ["company_id", "conversation_id", "turn_id"],
            [f"{TURNS}.company_id", f"{TURNS}.conversation_id", f"{TURNS}.id"],
            name="fk_assistant_messages_turn",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_assistant_messages_actor_user_id_users"
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_assistant_messages_company_id_id"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_assistant_messages_conversation_id_sequence"
        ),
        sa.UniqueConstraint("turn_id", "role", name="uq_assistant_messages_turn_id_role"),
        sa.CheckConstraint(one_of("role", MESSAGE_ROLES), name="ck_assistant_messages_role"),
        sa.CheckConstraint(MESSAGE_SHAPE, name="ck_assistant_messages_shape"),
        sa.CheckConstraint(
            f"conversation_state IS NULL OR {one_of('conversation_state', CONVERSATION_STATES)}",
            name="ck_assistant_messages_conversation_state",
        ),
        sa.CheckConstraint(
            f"sequence >= 1 AND sequence <= {2 * MAX_TURNS}",
            name="ck_assistant_messages_sequence",
        ),
        sa.CheckConstraint(MESSAGE_TEXT, name="ck_assistant_messages_text"),
        sa.CheckConstraint(MESSAGE_OUTCOME, name="ck_assistant_messages_outcome"),
    )

    op.create_table(
        EVALUATIONS,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("evaluation_schema", sa.String(length=60), nullable=False),
        sa.Column("availability", sa.String(length=40), nullable=False),
        sa.Column("matter", sa.String(length=30), nullable=False),
        sa.Column("workflow_key", sa.String(length=50), nullable=True),
        sa.Column("presentation", sa.String(length=20), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("has_review_requirement", sa.Boolean(), nullable=False),
        sa.Column("multiple_matters", sa.Boolean(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=16), nullable=False),
        sa.Column("knowledge_runtime_digest", sa.String(length=64), nullable=True),
        sa.Column("profile_digest", sa.String(length=64), nullable=True),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "withdrawn_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        _company_fk(EVALUATIONS),
        sa.ForeignKeyConstraint(
            ["company_id", "conversation_id", "turn_id"],
            [f"{TURNS}.company_id", f"{TURNS}.conversation_id", f"{TURNS}.id"],
            name="fk_assistant_turn_evaluations_turn",
        ),
        sa.UniqueConstraint("turn_id", name="uq_assistant_turn_evaluations_turn_id"),
        sa.CheckConstraint(
            one_of("availability", AVAILABILITIES),
            name="ck_assistant_turn_evaluations_availability",
        ),
        sa.CheckConstraint(one_of("matter", MATTERS), name="ck_assistant_turn_evaluations_matter"),
        sa.CheckConstraint(
            f"presentation IS NULL OR {one_of('presentation', PRESENTATIONS)}",
            name="ck_assistant_turn_evaluations_presentation",
        ),
        sa.CheckConstraint(
            f"outcome IS NULL OR {one_of('outcome', OUTCOME_KINDS)}",
            name="ck_assistant_turn_evaluations_outcome",
        ),
        sa.CheckConstraint(EVALUATION_IDENTITY, name="ck_assistant_turn_evaluations_identity"),
        sa.CheckConstraint(EVALUATION_RECORD, name="ck_assistant_turn_evaluations_record"),
        sa.CheckConstraint(WITHDRAWN, name="ck_assistant_turn_evaluations_withdrawn"),
    )
    op.create_index(
        "ix_assistant_turn_evaluations_conversation_id", EVALUATIONS, ["conversation_id"]
    )

    # Every existing submission was saved through a step's form.
    op.add_column(
        "workflow_submissions",
        sa.Column(
            "origin", sa.String(length=20), server_default=sa.text("'structured'"), nullable=False
        ),
    )
    op.add_column("workflow_submissions", sa.Column("source_message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_workflow_submissions_source_message",
        "workflow_submissions",
        MESSAGES,
        ["company_id", "source_message_id"],
        ["company_id", "id"],
    )
    op.create_check_constraint(
        "ck_workflow_submissions_origin", "workflow_submissions", SUBMISSION_ORIGIN
    )

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
    _set_schema_contract(9)


def _settle_privileges() -> None:
    """Remove whatever default privileges attached to the new tables (none intended)."""
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
    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {RUNTIME_ROLE}")
    op.execute(
        f"GRANT UPDATE ({', '.join(CONVERSATION_UPDATES)}) ON {CONVERSATIONS} TO {RUNTIME_ROLE}"
    )

    oids = ", ".join(f"'public.{table}'::regclass" for table in NEW_TABLES)
    runtime = f"(SELECT oid FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}')"
    updatable = ", ".join(f"'{column}'" for column in CONVERSATION_UPDATES)
    append_only = " OR ".join(
        f"has_any_column_privilege('{RUNTIME_ROLE}', 'public.{table}', 'UPDATE')"
        for table in APPEND_ONLY
    )
    operator = " OR ".join(
        f"has_any_column_privilege('{OPERATOR_ROLE}', 'public.{table}', 'SELECT, INSERT, UPDATE')"
        for table in NEW_TABLES
    )
    table_level = " OR ".join(
        f"has_table_privilege('{RUNTIME_ROLE}', 'public.{table}', "
        "'UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')"
        for table in NEW_TABLES
    )
    guard(
        f"""EXISTS (
            SELECT FROM pg_class c, aclexplode(c.relacl) a
            WHERE c.oid IN ({oids}) AND a.grantee <> c.relowner
              AND NOT (a.grantee = {runtime} AND a.privilege_type IN ('SELECT', 'INSERT')))
        OR EXISTS (
            SELECT FROM pg_attribute t
            WHERE t.attrelid = 'public.{CONVERSATIONS}'::regclass AND t.attnum > 0
              AND NOT t.attisdropped AND t.attname NOT IN ({updatable})
              AND has_column_privilege('{RUNTIME_ROLE}', t.attrelid, t.attnum, 'UPDATE'))
        OR EXISTS (
            SELECT FROM unnest(ARRAY[{updatable}]) AS u(name)
            WHERE NOT has_column_privilege('{RUNTIME_ROLE}', 'public.{CONVERSATIONS}', u.name,
                                           'UPDATE'))
        OR {append_only}
        OR {table_level}
        OR {operator}""",
        "unexpected privileges on the Ask HeroOS conversation tables",
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
    op.execute(f"LOCK TABLE workflow_submissions, {', '.join(NEW_TABLES)} IN ACCESS EXCLUSIVE MODE")
    guard(
        f"EXISTS (SELECT FROM {CONVERSATIONS}) "
        "OR EXISTS (SELECT FROM workflow_submissions WHERE origin <> 'structured')",
        "Ask HeroOS conversations exist; a rollback would delete them, so roll forward "
        "instead (deletion is decided by PRIV-020)",
    )
    _set_schema_contract(8)
    op.drop_constraint("ck_workflow_submissions_origin", "workflow_submissions", type_="check")
    op.drop_constraint(
        "fk_workflow_submissions_source_message", "workflow_submissions", type_="foreignkey"
    )
    op.drop_column("workflow_submissions", "source_message_id")
    op.drop_column("workflow_submissions", "origin")
    op.drop_index("ix_assistant_turn_evaluations_conversation_id", table_name=EVALUATIONS)
    op.drop_table(EVALUATIONS)
    op.drop_table(MESSAGES)
    op.drop_table(TURNS)
    op.drop_index("ix_assistant_conversations_company_id_updated_at", table_name=CONVERSATIONS)
    op.drop_table(CONVERSATIONS)
