"""Workflow entities attached to Cases (M2-01).

A ``WorkflowInstance`` is one guided workflow run for one Case. Answers are
saved as ``WorkflowSubmission`` groups of append-only ``CaseFact`` rows: a fact
is never updated, a later submission records a new value (``None`` = cleared).
Workflow progress is derived from these facts; nothing here encodes a legal
assessment. Migration ``75ec6db8b6c1`` adds RLS and the API grants.
"""

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

WORKFLOW_DISCIPLINARY: Final = "disciplinary"
WORKFLOW_KEYS: Final = (WORKFLOW_DISCIPLINARY,)

# JSONB on PostgreSQL; plain JSON for the SQLite stand-ins in unit tests. Python
# None is stored as SQL NULL (a cleared answer), not as a JSON null.
FactValue = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


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
