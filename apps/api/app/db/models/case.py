from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Case(TimestampMixin, Base):
    """Persistent real-world HR matter owned directly by a Company.

    Workflow state is intentionally absent; workflow instances attach to a Case
    in a later milestone.
    """

    __tablename__ = "cases"
    __table_args__ = (
        # Tenant-qualified candidate key so future dependents (e.g. workflow
        # instances) can enforce same-Company references.
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_cases_company_id_id",
        ),
        # Composite FK guarantees a Case can only reference a CaseSubject of the
        # same Company. Deleting the subject nulls only subject_id (PostgreSQL 15+),
        # leaving the tenant ownership column intact.
        ForeignKeyConstraint(
            ["company_id", "subject_id"],
            ["case_subjects.company_id", "case_subjects.id"],
            name="fk_cases_company_id_subject_id_case_subjects",
            ondelete="SET NULL (subject_id)",
        ),
        Index("ix_cases_subject_id", "subject_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )

    subject_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )

    case_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
