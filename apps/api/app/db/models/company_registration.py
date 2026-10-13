from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanyRegistration(Base):
    """One self-service founder registration (M1-10C). Read-only mapping.

    Written only by ``heroos_register_company`` (migration ``3f6c2a9d81b4``) in
    the transaction that creates the Company, and never changed (append-only
    triggers). At most one per User (person), which makes registration
    idempotent: a retry, a concurrent submission or another binding of the same
    person returns this row's Company. ``identity_id`` is the binding that
    registered. Tenant-owned (RLS ``tenant_isolation``); no application role
    holds any privilege on it.
    """

    __tablename__ = "company_registrations"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_company_registrations_user_id"),
        UniqueConstraint("company_id", name="uq_company_registrations_company_id"),
        ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
            name="fk_company_registrations_company_id_membership_id_memberships",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    identity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "user_identities.id",
            ondelete="RESTRICT",
            name="fk_company_registrations_identity_id_user_identities",
        ),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_company_registrations_user_id_users"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id",
            ondelete="RESTRICT",
            name="fk_company_registrations_company_id_companies",
        ),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
