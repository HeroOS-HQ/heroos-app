from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Customer-supplied licensing answer (M1-10C). The first onboarding question:
# DIFC, Other, or Not sure. An answer is information, never a legal conclusion.
LICENSING_DIFC: Final = "difc"
LICENSING_OTHER: Final = "other"
LICENSING_NOT_SURE: Final = "not_sure"
LICENSING_LOCATIONS: Final = (LICENSING_DIFC, LICENSING_OTHER, LICENSING_NOT_SURE)
MAX_LICENSING_AUTHORITY_LENGTH: Final = 120

# Company-level employment-law jurisdiction, set only by a trusted confirmation
# (platform operator). V1 supports UAE Federal / MOHRE and DIFC; ADGM and any
# other confirmed jurisdiction are represented so they can be refused clearly.
JURISDICTION_UAE_FEDERAL: Final = "uae_federal"
JURISDICTION_DIFC: Final = "difc"
JURISDICTION_ADGM: Final = "adgm"
JURISDICTION_OTHER: Final = "other"
EMPLOYMENT_JURISDICTIONS: Final = (
    JURISDICTION_UAE_FEDERAL,
    JURISDICTION_DIFC,
    JURISDICTION_ADGM,
    JURISDICTION_OTHER,
)


def _one_of_or_null(column: str, values: tuple[str, ...]) -> str:
    # Written out instead of IN (...): see app.db.models.audit.one_of.
    return f"{column} IS NULL OR " + " OR ".join(f"{column} = '{value}'" for value in values)


# Every branch is definite (IS [NOT] NULL guards): a comparison with NULL would
# yield NULL, and a CHECK that evaluates to NULL passes.
LICENSING_LOCATION_CHECK: Final = _one_of_or_null("licensing_location", LICENSING_LOCATIONS)
# An authority belongs only to the "Other" answer, and is never empty.
LICENSING_AUTHORITY_CHECK: Final = (
    "licensing_authority IS NULL OR (licensing_location IS NOT NULL "
    "AND licensing_location = 'other' AND licensing_authority <> '')"
)
EMPLOYMENT_JURISDICTION_CHECK: Final = _one_of_or_null(
    "employment_jurisdiction", EMPLOYMENT_JURISDICTIONS
)
# A confirmation is all-or-nothing and records the licensing answer it was made
# against: a definite answer (DIFC, or Other with its authority), never
# "not sure" and never a missing answer.
JURISDICTION_CONFIRMATION_CHECK: Final = (
    "(employment_jurisdiction IS NULL AND jurisdiction_confirmed_at IS NULL "
    "AND confirmed_licensing_location IS NULL AND confirmed_licensing_authority IS NULL) "
    "OR (employment_jurisdiction IS NOT NULL AND jurisdiction_confirmed_at IS NOT NULL "
    "AND confirmed_licensing_location IS NOT NULL "
    "AND ((confirmed_licensing_location = 'difc' AND confirmed_licensing_authority IS NULL) "
    "OR (confirmed_licensing_location = 'other' AND confirmed_licensing_authority IS NOT NULL "
    "AND confirmed_licensing_authority <> '')))"
)


class CompanyBlueprint(TimestampMixin, Base):
    """Company context for workflows and guidance; at most one per Company.

    Three separate kinds of information (M1-10C):

    - **Customer-supplied** (Company administrators, through the API): business
      profile and the licensing answer (``licensing_location``,
      ``licensing_authority``).
    - **Trusted confirmation** (platform operator only; the API role holds no
      write privilege on these columns): ``employment_jurisdiction``, the
      licensing answer it was confirmed against and ``jurisdiction_confirmed_at``.
    - **Derived readiness**: ``app.companies.jurisdiction.assess_jurisdiction``.
      A confirmation counts only while the customer's current licensing answer
      still equals the one it was confirmed against.

    ``primary_jurisdiction`` is the M1-04 placeholder: an unvalidated label kept
    unchanged for existing rows. It never establishes a jurisdiction and is not
    part of the API contract.

    Case-specific jurisdiction facts (for example where an employee works)
    are not stored here; workflows must still verify them per Case.
    """

    __tablename__ = "company_blueprints"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            name="uq_company_blueprints_company_id",
        ),
        CheckConstraint(
            "employee_count IS NULL OR employee_count >= 0",
            name="ck_company_blueprints_employee_count_nonnegative",
        ),
        CheckConstraint(LICENSING_LOCATION_CHECK, name="ck_company_blueprints_licensing_location"),
        CheckConstraint(
            LICENSING_AUTHORITY_CHECK, name="ck_company_blueprints_licensing_authority"
        ),
        CheckConstraint(
            EMPLOYMENT_JURISDICTION_CHECK, name="ck_company_blueprints_employment_jurisdiction"
        ),
        CheckConstraint(
            JURISDICTION_CONFIRMATION_CHECK, name="ck_company_blueprints_jurisdiction_confirmation"
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

    legal_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    primary_jurisdiction: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    industry: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    employee_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    licensing_location: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    licensing_authority: Mapped[str | None] = mapped_column(
        String(MAX_LICENSING_AUTHORITY_LENGTH),
        nullable=True,
    )

    # The trusted confirmation. ``FetchedValue()`` (no DDL; the database default
    # is NULL) keeps these columns out of every ORM INSERT that does not set
    # them, so the API role, which holds no INSERT or UPDATE privilege on them,
    # can still create a Blueprint. Setting one from API code is refused.
    employment_jurisdiction: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        server_default=FetchedValue(),
    )

    confirmed_licensing_location: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        server_default=FetchedValue(),
    )

    confirmed_licensing_authority: Mapped[str | None] = mapped_column(
        String(MAX_LICENSING_AUTHORITY_LENGTH),
        nullable=True,
        server_default=FetchedValue(),
    )

    jurisdiction_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=FetchedValue(),
    )
