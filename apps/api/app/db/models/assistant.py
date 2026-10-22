"""Ask HeroOS conversations (M2-NEW-07, migration ``8860b86ef2ba``): durable, Company-owned.

``AssistantConversation`` is one Ask HeroOS conversation of a Company. The
first turn that completes with a visible HeroOS reply creates it (opening an
empty conversation writes nothing). It attaches to at most one Case, once,
and never switches to another, and it keeps a bounded checkpoint: the minimal
trusted state the next turn starts from (``app.conversations.checkpoint``).
It belongs to the Company, not to the administrator who started it.

``AssistantTurn`` is one founder message and HeroOS's reply, in order
(``sequence`` is the conversation revision the turn produced), with the
client's ``turn_key``: a retried request replays the committed turn.

``AssistantMessage`` is what a person saw: the founder's words, or HeroOS's
visible reply with its safe next step, how the turn was handled and the
outcome card. Never a provider request or response, a prompt, a repair, a
model's reasoning or knowledge text.

``AssistantTurnEvaluation`` is the deterministic evaluation the turn produced
(``ConversationEvaluation.record()``, M2-NEW-06) with small queryable columns.
Server-only, and separate from ``workflow_evaluations`` (the structured intake
evaluation of a saved submission).

The API role only appends turns, messages and evaluations; on a conversation
it may change only its revision, Case attachment, workflow, title, checkpoint
and activity time. No cascade from Cases, turns or messages (PRIV-020).
"""

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.workflow import WORKFLOW_KEYS

# Stored vocabularies. Kept equal to the domain's (tests/conversations/test_model_contract.py).
MESSAGE_ROLES: Final = ("founder", "heroos")
CONVERSATION_STATES: Final = ("responded", "clarifying", "outside_approved_guidance")
OUTCOME_KINDS: Final = ("guidance", "warning", "block", "expert_review", "unavailable")
PRESENTATIONS: Final = ("guidance", "warning", "block", "expert_review")
MATTERS: Final = (
    "supported", "unsupported_hr", "outside_product_scope", "unclear", "confidential_request",
)  # fmt: skip
AVAILABILITIES: Final = (
    "ready", "knowledge_bundle_missing", "rule_bundle_missing", "execution_profile_missing",
    "incompatible_versions", "unsupported_executor", "privacy_capability_unavailable",
    "invalid_continuation", "internal_failure",
)  # fmt: skip
# Bounds on storage, not product rules (the API bounds the founder's message first).
MAX_TURNS: Final = 10000
MAX_TITLE: Final = 120
MAX_FOUNDER_CHARS: Final = 2000
MAX_HEROOS_CHARS: Final = 8000
MAX_NEXT_STEP_CHARS: Final = 1000
MAX_OUTCOME_BYTES: Final = 8192
MAX_CHECKPOINT_BYTES: Final = 8192
MAX_EVALUATION_BYTES: Final = 65536
MAX_WITHDRAWN: Final = 3

# JSONB on PostgreSQL; plain JSON for the SQLite stand-ins in unit tests.
Document = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return " OR ".join(f"{column} = '{value}'" for value in values)


# A founder message is the signed-in administrator's; a HeroOS message is no one's
# and carries how the turn was handled.
MESSAGE_SHAPE: Final = (
    "(role = 'founder' AND actor_user_id IS NOT NULL AND safe_next_step IS NULL "
    "AND conversation_state IS NULL AND outcome IS NULL) "
    "OR (role = 'heroos' AND actor_user_id IS NULL AND conversation_state IS NOT NULL)"
)


class AssistantConversation(TimestampMixin, Base):
    """One Ask HeroOS conversation (``updated_at``: its last completed turn)."""

    __tablename__ = "assistant_conversations"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_assistant_conversations_company_id_id"),
        # One conversation per Case, and a conversation holds at most one Case (the column).
        UniqueConstraint(
            "company_id", "case_id", name="uq_assistant_conversations_company_id_case_id"
        ),
        # Same-Company Case; no cascade (PRIV-020).
        ForeignKeyConstraint(
            ["company_id", "case_id"],
            ["cases.company_id", "cases.id"],
            name="fk_assistant_conversations_company_id_case_id_cases",
        ),
        CheckConstraint(
            f"workflow_key IS NULL OR {_one_of('workflow_key', WORKFLOW_KEYS)}",
            name="ck_assistant_conversations_workflow_key",
        ),
        # A Case is only ever attached for an established workflow.
        CheckConstraint(
            "case_id IS NULL OR workflow_key IS NOT NULL",
            name="ck_assistant_conversations_case_workflow",
        ),
        CheckConstraint(
            f"revision >= 0 AND revision <= {MAX_TURNS}", name="ck_assistant_conversations_revision"
        ),
        # The Company's conversations, most recent first (keyset pages on updated_at, id).
        Index(
            "ix_assistant_conversations_company_id_updated_at",
            "company_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
            name="fk_assistant_conversations_company_id_companies",
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_assistant_conversations_created_by_user_id_users"),
        nullable=False,
    )
    # Set once, by the turn that establishes a supported workflow; never changed after.
    case_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    workflow_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # A safe label (a validated topic or the workflow and a date): never a name.
    title: Mapped[str | None] = mapped_column(String(MAX_TITLE), nullable=True)
    # Optimistic concurrency: every completed turn increments it.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    # The bounded trusted state for the next turn (``heroos.assistant-checkpoint/1``).
    checkpoint: Mapped[Any] = mapped_column(Document, nullable=False)


class AssistantTurn(Base):
    """One founder message and HeroOS's reply (append-only)."""

    __tablename__ = "assistant_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id"],
            ["assistant_conversations.company_id", "assistant_conversations.id"],
            name="fk_assistant_turns_company_id_conversation_id",
        ),
        # Target of the messages' and evaluations' composite keys.
        UniqueConstraint(
            "company_id",
            "conversation_id",
            "id",
            name="uq_assistant_turns_company_id_conversation_id_id",
        ),
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_assistant_turns_conversation_id_sequence"
        ),
        # Idempotency, also for a first turn (which has no conversation yet).
        UniqueConstraint("company_id", "turn_key", name="uq_assistant_turns_company_id_turn_key"),
        CheckConstraint(
            f"sequence >= 1 AND sequence <= {MAX_TURNS}", name="ck_assistant_turns_sequence"
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_assistant_turns_company_id_companies"
        ),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The conversation revision this turn produced (1 for the first turn).
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Client-generated per send attempt; a retry sends the same key.
    turn_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The authenticated administrator who sent it (from the session, never the request).
    actor_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_assistant_turns_actor_user_id_users"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssistantMessage(Base):
    """What a person saw: a founder message or HeroOS's visible reply (append-only)."""

    __tablename__ = "assistant_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id", "turn_id"],
            [
                "assistant_turns.company_id",
                "assistant_turns.conversation_id",
                "assistant_turns.id",
            ],
            name="fk_assistant_messages_turn",
        ),
        # Target of the assistant-origin submissions' provenance key.
        UniqueConstraint("company_id", "id", name="uq_assistant_messages_company_id_id"),
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_assistant_messages_conversation_id_sequence"
        ),
        UniqueConstraint("turn_id", "role", name="uq_assistant_messages_turn_id_role"),
        CheckConstraint(_one_of("role", MESSAGE_ROLES), name="ck_assistant_messages_role"),
        CheckConstraint(MESSAGE_SHAPE, name="ck_assistant_messages_shape"),
        CheckConstraint(
            f"conversation_state IS NULL OR {_one_of('conversation_state', CONVERSATION_STATES)}",
            name="ck_assistant_messages_conversation_state",
        ),
        CheckConstraint(
            f"sequence >= 1 AND sequence <= {2 * MAX_TURNS}",
            name="ck_assistant_messages_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_assistant_messages_company_id_companies"
        ),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    turn_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # Stable order across the conversation (founder then HeroOS, turn after turn).
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_assistant_messages_actor_user_id_users"),
        nullable=True,
    )
    # Exactly what was shown, stored as it was (never normalized).
    content: Mapped[str] = mapped_column(Text, nullable=False)
    safe_next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # The outcome card as shown: {kind, title, message, items: [{kind, text}]}.
    outcome: Mapped[Any] = mapped_column(Document, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssistantTurnEvaluation(Base):
    """The deterministic evaluation one turn produced (append-only; server-only)."""

    __tablename__ = "assistant_turn_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "conversation_id", "turn_id"],
            [
                "assistant_turns.company_id",
                "assistant_turns.conversation_id",
                "assistant_turns.id",
            ],
            name="fk_assistant_turn_evaluations_turn",
        ),
        UniqueConstraint("turn_id", name="uq_assistant_turn_evaluations_turn_id"),
        CheckConstraint(
            _one_of("availability", AVAILABILITIES),
            name="ck_assistant_turn_evaluations_availability",
        ),
        CheckConstraint(_one_of("matter", MATTERS), name="ck_assistant_turn_evaluations_matter"),
        CheckConstraint(
            f"presentation IS NULL OR {_one_of('presentation', PRESENTATIONS)}",
            name="ck_assistant_turn_evaluations_presentation",
        ),
        CheckConstraint(
            f"outcome IS NULL OR {_one_of('outcome', OUTCOME_KINDS)}",
            name="ck_assistant_turn_evaluations_outcome",
        ),
        Index("ix_assistant_turn_evaluations_conversation_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
            name="fk_assistant_turn_evaluations_company_id_companies",
        ),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    turn_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The record's schema (``heroos.conversation-evaluation/1``).
    evaluation_schema: Mapped[str] = mapped_column(String(60), nullable=False)
    # Small queryable columns; the full record stays in ``record``.
    availability: Mapped[str] = mapped_column(String(40), nullable=False)
    matter: Mapped[str] = mapped_column(String(30), nullable=False)
    workflow_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    presentation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The outcome card shown (``unavailable`` when the checks couldn't run).
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    has_review_requirement: Mapped[bool] = mapped_column(Boolean, nullable=False)
    multiple_matters: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The execution snapshot and the artifacts it pinned (identities, never content).
    snapshot_id: Mapped[str] = mapped_column(String(16), nullable=False)
    knowledge_runtime_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record: Mapped[Any] = mapped_column(Document, nullable=False)
    # The decisions the founder explicitly withdrew in this turn (option ids): with the
    # records, what makes the current active reviews rebuildable.
    withdrawn_actions: Mapped[Any] = mapped_column(Document, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
