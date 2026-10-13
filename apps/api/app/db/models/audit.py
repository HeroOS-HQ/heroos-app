"""Security audit events for identity and Membership changes (ADR-008).

Read-only mappings. No application role can insert, update or delete these
rows: they are written only by the ``SECURITY DEFINER`` triggers on ``users``,
``user_identities`` and ``memberships`` (migration ``b8a11c15ed91``), in the
same transaction as the change they record.

- ``db_role`` is the authenticated PostgreSQL login (``session_user``), not
  something a caller can claim.
- ``actor_reference`` is a validated change reference (issue key such as
  ``HER-230``, or ``alembic:<revision>`` for migrations); never free text.
- No external issuer or subject is copied here: events reference the binding
  ``identity_id``.

Retention is undecided (PRIV-005); nothing purges these rows.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def one_of(column: str, values: tuple[str, ...]) -> str:
    """CHECK expression ``column = v1 OR ...``.

    Written out instead of ``IN (...)``: PostgreSQL deparses a varchar ``IN``
    check differently after a dump/restore, which would break the restore
    verification's exact catalog comparison.
    """
    return " OR ".join(f"{column} = '{value}'" for value in values)


IDENTITY_EVENT_TYPES = (
    "user_created",
    "user_suspended",
    "user_reactivated",
    "identity_bound",
    "identity_revoked",
    "identity_reactivated",
)
MEMBERSHIP_EVENT_TYPES = ("membership_granted", "membership_revoked", "membership_reactivated")
ACTOR_KINDS = ("owner", "operator", "api")


ACTOR_REFERENCE_CHECK = (
    "actor_reference ~ '^[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}$' "
    "OR (actor_kind = 'owner' AND actor_reference ~ '^alembic:[0-9a-f]{12}$')"
)


class IdentityEvent(Base):
    __tablename__ = "identity_events"
    __table_args__ = (
        CheckConstraint(
            one_of("event_type", IDENTITY_EVENT_TYPES),
            name="ck_identity_events_event_type",
        ),
        CheckConstraint(
            one_of("actor_kind", ACTOR_KINDS),
            name="ck_identity_events_actor_kind",
        ),
        CheckConstraint(ACTOR_REFERENCE_CHECK, name="ck_identity_events_actor_reference"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    txid: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_identity_events_user_id_users"),
        nullable=False,
    )
    identity_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "user_identities.id",
            ondelete="RESTRICT",
            name="fk_identity_events_identity_id_user_identities",
        ),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    db_role: Mapped[str] = mapped_column(String(63), nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(64), nullable=False)


class MembershipEvent(Base):
    """Tenant-owned: RLS ``tenant_isolation`` like every Company table."""

    __tablename__ = "membership_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["memberships.company_id", "memberships.id"],
            ondelete="RESTRICT",
            name="fk_membership_events_company_id_membership_id_memberships",
        ),
        CheckConstraint(
            one_of("event_type", MEMBERSHIP_EVENT_TYPES),
            name="ck_membership_events_event_type",
        ),
        CheckConstraint(
            one_of("actor_kind", ACTOR_KINDS),
            name="ck_membership_events_actor_kind",
        ),
        CheckConstraint(ACTOR_REFERENCE_CHECK, name="ck_membership_events_actor_reference"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    txid: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("txid_current()")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "companies.id", ondelete="RESTRICT", name="fk_membership_events_company_id_companies"
        ),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_membership_events_user_id_users"),
        nullable=False,
    )
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    db_role: Mapped[str] = mapped_column(String(63), nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(64), nullable=False)
