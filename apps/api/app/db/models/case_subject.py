from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CaseSubject(Base):
    """Lightweight tenant-owned person involved in a case (employee or candidate).

    Deliberately minimal: HeroOS is not an HRIS, so no sensitive HR profile data
    (DOB, salary, passport/visa, address, medical) belongs here.
    """

    __tablename__ = "case_subjects"
    __table_args__ = (
        # Tenant-qualified candidate key so dependent tables can enforce that a
        # reference never crosses Company boundaries.
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_case_subjects_company_id_id",
        ),
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

    subject_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    display_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
