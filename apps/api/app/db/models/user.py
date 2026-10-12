from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

USER_ACTIVE: Final = "active"
USER_SUSPENDED: Final = "suspended"


class User(TimestampMixin, Base):
    """Stable internal HeroOS identity (ADR-008).

    ``id`` never changes, whichever identity provider authenticates the person.
    External identities live in ``user_identities``; this table holds no
    provider subject and no personal data.

    ``status`` is global: a suspended User is denied in every Company, by the
    application and by Row-Level Security for the API role. Suspension is not
    deletion (PRIV-008, PRIV-020).
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status = 'active' OR status = 'suspended'", name="ck_users_status"),
        CheckConstraint(
            "(status = 'suspended') = (suspended_at IS NOT NULL)", name="ck_users_suspended_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=USER_ACTIVE,
        server_default=text("'active'"),
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
