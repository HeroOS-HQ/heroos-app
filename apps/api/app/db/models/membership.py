from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MEMBERSHIP_ACTIVE: Final = "active"
MEMBERSHIP_REVOKED: Final = "revoked"


class Membership(TimestampMixin, Base):
    """A User's access to one Company.

    Only an ``active`` Membership authorizes. Revocation keeps the row
    (``status = 'revoked'``); it is not deletion (PRIV-020).
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "user_id",
            name="uq_memberships_company_user",
        ),
        # Tenant-qualified candidate key for same-Company references
        # (membership_events).
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_memberships_company_id_id",
        ),
        CheckConstraint("status = 'active' OR status = 'revoked'", name="ck_memberships_status"),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_memberships_revoked_at"
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

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MEMBERSHIP_ACTIVE,
        server_default=text("'active'"),
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
