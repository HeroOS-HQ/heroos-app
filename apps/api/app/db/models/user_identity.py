from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

IDENTITY_ACTIVE: Final = "active"
IDENTITY_REVOKED: Final = "revoked"

# Column limits; `subject` matches app.auth.providers.base.MAX_SUBJECT_LENGTH.
MAX_ISSUER_LENGTH: Final = 512
MAX_SUBJECT_LENGTH: Final = 255


class UserIdentity(TimestampMixin, Base):
    """An external identity bound to a HeroOS User (ADR-008).

    Keyed by the exact ``(issuer, subject)`` pair a provider verified: never by
    email, never normalized. A pair is unique for all time, so a revoked
    binding can never be re-bound to another User. ``user_id``, ``issuer`` and
    ``subject`` are immutable (database trigger, column grants).

    ``subject`` is pseudonymous personal data. It is stored here only; audit
    events reference the binding ``id``.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
        CheckConstraint(
            "status = 'active' OR status = 'revoked'", name="ck_user_identities_status"
        ),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)",
            name="ck_user_identities_revoked_at",
        ),
        CheckConstraint("issuer <> ''", name="ck_user_identities_issuer_not_empty"),
        CheckConstraint("subject <> ''", name="ck_user_identities_subject_not_empty"),
        # At most one active binding per User and issuer (an Auth0 and a
        # Cognito binding may be active together during an IdP migration).
        Index(
            "uq_user_identities_active_user_issuer",
            "user_id",
            "issuer",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_identities_user_id_users"),
        nullable=False,
    )

    issuer: Mapped[str] = mapped_column(String(MAX_ISSUER_LENGTH), nullable=False)

    subject: Mapped[str] = mapped_column(String(MAX_SUBJECT_LENGTH), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=IDENTITY_ACTIVE,
        server_default=text("'active'"),
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
