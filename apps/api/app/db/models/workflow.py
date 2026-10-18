"""Workflow entities attached to Cases (M2-01, M2-02).

A ``WorkflowInstance`` is one guided workflow run for one Case. Answers are
saved as ``WorkflowSubmission`` groups of append-only ``CaseFact`` rows: a fact
is never updated, a later submission records a new value (``None`` = cleared).
Workflow progress is derived from these facts; nothing here encodes a legal
assessment. Migration ``75ec6db8b6c1`` adds RLS and the API grants.

``WorkflowEvaluation`` (M2-02, migration ``e64497d997d8``) is the append-only
record of the intake evaluation each saved submission produced: the Case
status, hold and its reason, the resolved Case jurisdiction, the screening
state and every rule's result with the structured inputs it read, plus the
definition and rule-set versions used. The current state is always recomputed
on read; these rows are the trace.

``WorkflowProgressEvent`` (M2-03, migration ``8d217d768395``) is the append-only
record of workflow progression: the employer's pathway choices, stages started
and completed, transitions refused, and escalations recorded, each with the
decision, its reason codes, the warnings acknowledged and the rule bundle
(id, version, digest) that decided it. The Case's position is derived from
these rows on read; nothing here is a mutable snapshot.

``WorkflowDecisionRecord`` (M2-04, migration ``c4a7e2d9b310``) is the
append-only record of what the employer reports about its own handling of the
Case: a factual record in a safe category, who the employer says is
responsible, the date, an explanation and references to evidence the employer
holds (never the evidence itself). A correction or clarification is a new row
that supersedes exactly one earlier row of the same chain; nothing is updated.
A record is the employer's account, never a workflow authorization: it moves
no stage and releases no hold.
"""

from datetime import date, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

WORKFLOW_DISCIPLINARY: Final = "disciplinary"
WORKFLOW_KEYS: Final = (WORKFLOW_DISCIPLINARY,)

# Stored intake evaluation vocabularies (app.workflows.intake). Written out as
# ``a = 'x' OR ...`` in CHECK constraints (see app.db.models.audit.one_of).
EVALUATION_STATUSES: Final = (
    "case_created",
    "intake_in_progress",
    "awaiting_jurisdiction",
    "screening_not_cleared",
    "screening_unavailable",
    "held_for_specialist_review",
    "intake_recorded",
)
EVALUATION_HOLDS: Final = ("jurisdiction", "specialist_review")
EVALUATION_HOLD_REASONS: Final = (
    "high_risk_factors",
    "jurisdiction_different",
    "jurisdiction_unsupported",
    "screening_not_covered",
    "earlier_escalation",
    "company_jurisdiction_unconfirmed",
    "case_jurisdiction_not_sure",
    "case_jurisdiction_outdated",
)
EVALUATION_JURISDICTIONS: Final = ("uae_federal", "difc")
EVALUATION_SCREENING: Final = (
    "not_applicable",
    "disabled",
    "not_started",
    "incomplete",
    "not_cleared",
    "cleared",
    "positive",
)
# A bound on the trace, not a product rule (results hold codes and enumerated
# answers only, never free text).
MAX_EVALUATION_RESULTS_BYTES: Final = 65536

# Stored progression vocabularies (app.workflows.progression.engine).
PROGRESS_EVENT_KINDS: Final = (
    "pathway_selected",
    "stage_started",
    "stage_completed",
    "transition_rejected",
    "escalation_recorded",
)
# Events that move the Case's position (one per instance revision).
PROGRESS_APPLIED_KINDS: Final = ("pathway_selected", "stage_started", "stage_completed")
PROGRESS_DECISIONS: Final = ("allow", "warn", "block", "escalate")
# The Disciplinary pathways (app.workflows.progression.spec).
PROGRESS_PATHWAYS: Final = ("less_serious", "serious", "undetermined")
# A bound on the stored reason codes, not a product rule.
MAX_PROGRESS_DETAIL_BYTES: Final = 16384
# What each kind of event must carry: position changes are allowed (or warned
# and acknowledged) employer requests; refusals are blocked or escalated
# employer requests; escalations found by a save carry no request.
PROGRESS_EVENT_SHAPE: Final = (
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

# Stored employer decision-record vocabularies (app.workflows.decisions). Only
# factual categories that authorize nothing: warnings, suspensions, penalties,
# dismissals, findings and specialist approvals are deliberately absent, so the
# database itself refuses them.
DECISION_CATEGORIES: Final = (
    "internal_review_completed",
    "information_requested",
    "meeting_recorded",
    "employer_observation",
    "internal_pause_or_follow_up",
    "other_note",
)
# original: a first record; correction / clarification: supersedes one record.
DECISION_RELATIONS: Final = ("original", "correction", "clarification")
# recorder: the signed-in administrator; other: someone the employer names by role
# (an unverified employer statement, never the authenticated actor).
DECISION_MAKERS: Final = ("recorder", "other")
# held: the employer holds evidence (described by reference); none: it says none
# is available; not_sure: it doesn't know yet. HeroOS never holds or checks it.
DECISION_EVIDENCE_STATUSES: Final = ("held", "none", "not_sure")
DECISION_EVIDENCE_KINDS: Final = ("internal_document", "meeting_note", "policy", "other")
# The progression status when the record was made (app.workflows.progression.engine).
PROGRESSION_STATUSES: Final = (
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
# Bounds on employer-entered text (characters) and on the evidence references.
MAX_DECISION_SUMMARY: Final = 200
MAX_DECISION_EXPLANATION: Final = 4000
MAX_DECISION_MAKER_ROLE: Final = 120
MAX_DECISION_CHANGE_REASON: Final = 500
MAX_DECISION_EVIDENCE_ITEMS: Final = 10
MAX_EVIDENCE_DESCRIPTION: Final = 300
MAX_EVIDENCE_REFERENCE: Final = 200
# A storage backstop for the evidence references, not a product rule.
MAX_DECISION_EVIDENCE_BYTES: Final = 8192
# A first record starts its own chain; a later version supersedes one record of
# the same chain (the foreign key below keeps it in the chain, Case and Company)
# and says why it was made.
DECISION_RECORD_SHAPE: Final = (
    "(relation = 'original' AND supersedes_id IS NULL AND chain_id = id "
    "AND change_reason IS NULL) "
    "OR ((relation = 'correction' OR relation = 'clarification') "
    "AND supersedes_id IS NOT NULL AND supersedes_id <> id AND chain_id <> id "
    "AND change_reason IS NOT NULL)"
)
DECISION_MAKER_SHAPE: Final = (
    "(decision_maker = 'recorder' AND decision_maker_role IS NULL) "
    "OR (decision_maker = 'other' AND decision_maker_role IS NOT NULL)"
)

# JSONB on PostgreSQL; plain JSON for the SQLite stand-ins in unit tests. Python
# None is stored as SQL NULL (a cleared answer), not as a JSON null.
FactValue = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
EvaluationResults = JSON().with_variant(JSONB(), "postgresql")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return " OR ".join(f"{column} = '{value}'" for value in values)


class WorkflowInstance(TimestampMixin, Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_workflow_instances_company_id_id"),
        UniqueConstraint("company_id", "case_id", name="uq_workflow_instances_company_id_case_id"),
        UniqueConstraint(
            "company_id", "request_key", name="uq_workflow_instances_company_id_request_key"
        ),
        # Same-Company Case; deliberately no cascade from Cases (PRIV-020).
        ForeignKeyConstraint(
            ["company_id", "case_id"],
            ["cases.company_id", "cases.id"],
            name="fk_workflow_instances_company_id_case_id_cases",
        ),
        CheckConstraint(
            "workflow_key IN ('disciplinary')", name="ck_workflow_instances_workflow_key"
        ),
        CheckConstraint("definition_version >= 1", name="ck_workflow_instances_definition_version"),
        CheckConstraint("revision >= 0", name="ck_workflow_instances_revision"),
        Index("ix_workflow_instances_company_id_workflow_key", "company_id", "workflow_key"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_workflow_instances_company_id_companies"
        ),
        nullable=False,
    )
    case_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(50), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optimistic concurrency: every saved answer group increments it.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    # Client-generated idempotency key of the request that created the Case.
    request_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_workflow_instances_created_by_user_id_users"),
        nullable=False,
    )


class WorkflowSubmission(Base):
    __tablename__ = "workflow_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_submissions_company_id_instance_id",
        ),
        UniqueConstraint(
            "company_id",
            "instance_id",
            "id",
            name="uq_workflow_submissions_company_id_instance_id_id",
        ),
        UniqueConstraint(
            "instance_id", "revision", name="uq_workflow_submissions_instance_id_revision"
        ),
        UniqueConstraint(
            "instance_id",
            "idempotency_key",
            name="uq_workflow_submissions_instance_id_idempotency_key",
        ),
        CheckConstraint("revision >= 1", name="ck_workflow_submissions_revision"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_workflow_submissions_company_id_companies"
        ),
        nullable=False,
    )
    instance_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    step_key: Mapped[str] = mapped_column(String(50), nullable=False)
    # The instance revision this submission produced.
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    submitted_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_workflow_submissions_submitted_by_user_id_users"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseFact(Base):
    __tablename__ = "case_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_case_facts_company_id_instance_id_submission_id",
        ),
        UniqueConstraint("submission_id", "fact_key", name="uq_case_facts_submission_id_fact_key"),
        Index("ix_case_facts_instance_id_fact_key", "instance_id", "fact_key"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE", name="fk_case_facts_company_id_companies"),
        nullable=False,
    )
    instance_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    submission_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # None: the answer was cleared by this submission.
    value: Mapped[Any] = mapped_column(FactValue, nullable=True)


class WorkflowEvaluation(Base):
    """The intake evaluation one saved submission produced (append-only)."""

    __tablename__ = "workflow_evaluations"
    __table_args__ = (
        # The submission of the same Company and the same instance.
        ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_workflow_evaluations_company_id_instance_id_submission_id",
        ),
        UniqueConstraint("submission_id", name="uq_workflow_evaluations_submission_id"),
        CheckConstraint(
            _one_of("status", EVALUATION_STATUSES), name="ck_workflow_evaluations_status"
        ),
        CheckConstraint(
            "(hold IS NULL AND hold_reason IS NULL) OR (hold IS NOT NULL AND hold_reason IS NOT "
            f"NULL AND ({_one_of('hold', EVALUATION_HOLDS)}) "
            f"AND ({_one_of('hold_reason', EVALUATION_HOLD_REASONS)}))",
            name="ck_workflow_evaluations_hold",
        ),
        CheckConstraint(
            f"jurisdiction IS NULL OR {_one_of('jurisdiction', EVALUATION_JURISDICTIONS)}",
            name="ck_workflow_evaluations_jurisdiction",
        ),
        CheckConstraint(
            _one_of("screening", EVALUATION_SCREENING), name="ck_workflow_evaluations_screening"
        ),
        Index("ix_workflow_evaluations_instance_id", "instance_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="CASCADE", name="fk_workflow_evaluations_company_id_companies"
        ),
        nullable=False,
    )
    instance_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    submission_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    ruleset_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    hold: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The resolved Case jurisdiction; None while unresolved.
    jurisdiction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    screening: Mapped[str] = mapped_column(String(20), nullable=False)
    # Every rule's result, in rule-set order (app.workflows.intake).
    results: Mapped[Any] = mapped_column(EvaluationResults, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowProgressEvent(Base):
    """One progression event of a workflow instance (append-only; codes only)."""

    __tablename__ = "workflow_progress_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_progress_events_company_id_instance_id",
        ),
        # An escalation found while saving answers points at that submission.
        ForeignKeyConstraint(
            ["company_id", "instance_id", "submission_id"],
            [
                "workflow_submissions.company_id",
                "workflow_submissions.instance_id",
                "workflow_submissions.id",
            ],
            name="fk_workflow_progress_events_submission",
        ),
        CheckConstraint(
            _one_of("kind", PROGRESS_EVENT_KINDS), name="ck_workflow_progress_events_kind"
        ),
        CheckConstraint(
            _one_of("decision", PROGRESS_DECISIONS), name="ck_workflow_progress_events_decision"
        ),
        CheckConstraint(PROGRESS_EVENT_SHAPE, name="ck_workflow_progress_events_shape"),
        CheckConstraint(
            f"(pathway IS NULL OR {_one_of('pathway', PROGRESS_PATHWAYS)}) AND "
            f"(previous_pathway IS NULL OR {_one_of('previous_pathway', PROGRESS_PATHWAYS)})",
            name="ck_workflow_progress_events_pathway",
        ),
        CheckConstraint("revision >= 0", name="ck_workflow_progress_events_revision"),
        CheckConstraint(
            "definition_version >= 1", name="ck_workflow_progress_events_definition_version"
        ),
        Index("ix_workflow_progress_events_instance_id", "instance_id"),
        # Idempotency: one event per employer request.
        Index(
            "uq_workflow_progress_events_instance_id_request_key",
            "instance_id",
            "request_key",
            unique=True,
            postgresql_where="request_key IS NOT NULL",
            sqlite_where=text("request_key IS NOT NULL"),
        ),
        # One position change per instance revision.
        Index(
            "uq_workflow_progress_events_instance_id_revision",
            "instance_id",
            "revision",
            unique=True,
            postgresql_where=_one_of("kind", PROGRESS_APPLIED_KINDS),
            sqlite_where=text(_one_of("kind", PROGRESS_APPLIED_KINDS)),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
            name="fk_workflow_progress_events_company_id_companies",
        ),
        nullable=False,
    )
    instance_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # "pathway:<key>", "start:<stage>" or "complete:<stage>".
    transition: Mapped[str] = mapped_column(String(100), nullable=False)
    # pathway_selected: the choice recorded and the one it replaced.
    pathway: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_pathway: Mapped[str | None] = mapped_column(String(30), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    # Engine gate codes and bundle rule keys with their outcome; never answers.
    reasons: Mapped[Any] = mapped_column(EvaluationResults, nullable=False)
    # The warning rule keys the employer acknowledged.
    acknowledged: Mapped[Any] = mapped_column(EvaluationResults, nullable=False)
    # Applied: the revision this event produced; otherwise the revision it was decided at.
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # The employer request (idempotency key); None for an escalation found by a save.
    request_key: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    submission_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_workflow_progress_events_actor_user_id_users"),
        nullable=False,
    )
    bundle_id: Mapped[str] = mapped_column(String(50), nullable=False)
    bundle_version: Mapped[str] = mapped_column(String(50), nullable=False)
    bundle_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The intake status when the event was decided (e.g. held for specialist review).
    intake_status: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowDecisionRecord(Base):
    """One employer decision record or observation (append-only; supersede, never update)."""

    __tablename__ = "workflow_decision_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "instance_id"],
            ["workflow_instances.company_id", "workflow_instances.id"],
            name="fk_workflow_decision_records_company_id_instance_id",
        ),
        # The target of a correction: a record of the same chain, Case and Company.
        UniqueConstraint(
            "company_id",
            "instance_id",
            "chain_id",
            "id",
            name="uq_workflow_decision_records_chain_member",
        ),
        ForeignKeyConstraint(
            ["company_id", "instance_id", "chain_id", "supersedes_id"],
            [
                "workflow_decision_records.company_id",
                "workflow_decision_records.instance_id",
                "workflow_decision_records.chain_id",
                "workflow_decision_records.id",
            ],
            name="fk_workflow_decision_records_supersedes",
        ),
        # A record is superseded at most once: every chain is a single line.
        UniqueConstraint("supersedes_id", name="uq_workflow_decision_records_supersedes_id"),
        # Idempotency: one record per employer request.
        UniqueConstraint(
            "instance_id",
            "request_key",
            name="uq_workflow_decision_records_instance_id_request_key",
        ),
        # Every record produced its own instance revision.
        UniqueConstraint(
            "instance_id", "revision", name="uq_workflow_decision_records_instance_id_revision"
        ),
        CheckConstraint(
            _one_of("category", DECISION_CATEGORIES), name="ck_workflow_decision_records_category"
        ),
        CheckConstraint(
            _one_of("relation", DECISION_RELATIONS), name="ck_workflow_decision_records_relation"
        ),
        CheckConstraint(DECISION_RECORD_SHAPE, name="ck_workflow_decision_records_shape"),
        CheckConstraint(
            f"({_one_of('decision_maker', DECISION_MAKERS)}) AND ({DECISION_MAKER_SHAPE})",
            name="ck_workflow_decision_records_decision_maker",
        ),
        CheckConstraint(
            _one_of("evidence_status", DECISION_EVIDENCE_STATUSES),
            name="ck_workflow_decision_records_evidence_status",
        ),
        CheckConstraint(
            _one_of("intake_status", EVALUATION_STATUSES),
            name="ck_workflow_decision_records_intake_status",
        ),
        CheckConstraint(
            _one_of("progression_status", PROGRESSION_STATUSES),
            name="ck_workflow_decision_records_progression_status",
        ),
        CheckConstraint("revision >= 1", name="ck_workflow_decision_records_revision"),
        CheckConstraint(
            "definition_version >= 1", name="ck_workflow_decision_records_definition_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="CASCADE",
            name="fk_workflow_decision_records_company_id_companies",
        ),
        nullable=False,
    )
    instance_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The first record of the chain (its own id for a first record).
    chain_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The record this one corrects or clarifies; None for a first record.
    supersedes_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    relation: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    # Employer-entered text, stored exactly as sent (validated, never normalized).
    summary: Mapped[str] = mapped_column(String(MAX_DECISION_SUMMARY), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    # The date the employer says the decision or event happened.
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    decision_maker: Mapped[str] = mapped_column(String(20), nullable=False)
    # "other": the role the employer names (unverified); never a HeroOS User.
    decision_maker_role: Mapped[str | None] = mapped_column(
        String(MAX_DECISION_MAKER_ROLE), nullable=True
    )
    evidence_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # References to evidence the employer holds: [{kind, description, reference}].
    evidence: Mapped[Any] = mapped_column(EvaluationResults, nullable=False)
    # Why a correction or clarification was made; None for a first record.
    change_reason: Mapped[str | None] = mapped_column(
        String(MAX_DECISION_CHANGE_REASON), nullable=True
    )
    # The instance revision this record produced (optimistic concurrency).
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # The authenticated administrator (from the session, never from the request).
    recorded_by_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", name="fk_workflow_decision_records_recorded_by_user_id_users"),
        nullable=False,
    )
    # The workflow context when it was recorded (codes only).
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    intake_status: Mapped[str] = mapped_column(String(40), nullable=False)
    progression_status: Mapped[str] = mapped_column(String(30), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
