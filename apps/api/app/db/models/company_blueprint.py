from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
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


# Company context (M2-NEW-03, migration D5): customer-supplied like the
# business profile. Limits are enforced by the API (app.companies.blueprint)
# and again by the database (the text checks are in the migration only: they
# use PostgreSQL functions).
MAX_WEBSITE_URL_LENGTH: Final = 500
MAX_COMPANY_SUMMARY_LENGTH: Final = 2000
MAX_POLICY_CONTEXT_LENGTH: Final = 1000
MAX_HR_SUPPORT_NOTES_LENGTH: Final = 500

# Does the company have HR policies? NULL is "not answered".
POLICIES_YES: Final = "yes"
POLICIES_NO: Final = "no"
POLICIES_NOT_SURE: Final = "not_sure"
POLICIES_EXIST_VALUES: Final = (POLICIES_YES, POLICIES_NO, POLICIES_NOT_SURE)

# How the company handles HR today. NULL is "not answered".
HR_SUPPORT_VALUES: Final = ("none", "internal", "external", "mixed", "other")


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
POLICIES_EXIST_CHECK: Final = _one_of_or_null("policies_exist", POLICIES_EXIST_VALUES)
HR_SUPPORT_CHECK: Final = _one_of_or_null("hr_support", HR_SUPPORT_VALUES)


class CompanyBlueprint(TimestampMixin, Base):
    """Company context for workflows and guidance; at most one per Company.

    Three separate kinds of information (M1-10C):

    - **Customer-supplied** (Company administrators, through the API): business
      profile, the licensing answer (``licensing_location``,
      ``licensing_authority``) and, since M2-NEW-03, the company context:
      website, summary, policies, HR support and the primary contact (a
      Membership of the same Company; a Company-qualified foreign key).
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

    The company display name is ``companies.name``, never copied here.
    ``app.companies.blueprint`` reads all of it as one canonical context.
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
        CheckConstraint(POLICIES_EXIST_CHECK, name="ck_company_blueprints_policies_exist"),
        CheckConstraint(HR_SUPPORT_CHECK, name="ck_company_blueprints_hr_support"),
        # The primary contact is a Membership of this Company: never another's.
        ForeignKeyConstraint(
            ["company_id", "primary_contact_membership_id"],
            ["memberships.company_id", "memberships.id"],
            name="fk_company_blueprints_company_id_primary_contact_membership_id",
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

    # Company context (M2-NEW-03).
    website_url: Mapped[str | None] = mapped_column(
        String(MAX_WEBSITE_URL_LENGTH),
        nullable=True,
    )

    company_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    policies_exist: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    policy_context: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    hr_support: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    hr_support_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    primary_contact_membership_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
