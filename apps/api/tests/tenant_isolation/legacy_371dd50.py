"""Frozen copy of the database-facing authorization code of the previous API.

Source: ``371dd500ae1bd253cd402d0cbcf04b1ec005fe45`` (the deployed baseline before
M1-10B): ``app/db/base.py``, ``app/db/models/{company,user,membership}.py`` and
``resolve_user`` / ``authorize_company`` from ``app/auth/service.py``. Copied
verbatim except for import paths and an own declarative base, so the old ORM
mapping (including ``users.identity_subject``) is exactly what that API would
send to PostgreSQL. ``app.tenancy.context`` is unchanged since that revision and
is imported as is.

Used only by ``test_identity_migration.py`` to prove what the *old* API does on
the B1a and B1b schemas. Do not modify: it is evidence, not code to maintain.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.tenancy.context import TenantContextError, set_tenant_context


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    identity_subject: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "user_id",
            name="uq_memberships_company_user",
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


class AuthorizationError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    subject: str
    issuer: str


@dataclass(frozen=True, slots=True)
class AuthenticatedCompanyContext:
    user_id: UUID
    company_id: UUID
    membership_id: UUID
    identity_subject: str


def resolve_user(db: Session, identity: VerifiedIdentity) -> User:
    user = db.scalar(select(User).where(User.identity_subject == identity.subject))
    if user is None:
        raise AuthorizationError("no HeroOS user for verified identity")
    return user


def authorize_company(db: Session, user: User, company_id: UUID) -> AuthenticatedCompanyContext:
    user_id = user.id
    identity_subject = user.identity_subject
    try:
        set_tenant_context(db, company_id)
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.company_id == company_id,
            )
        )
        authorized = None if membership is None else (membership.id, membership.company_id)
    except TenantContextError:
        raise AuthorizationError("invalid requested company") from None
    finally:
        db.rollback()

    if authorized is None:
        raise AuthorizationError("no membership for requested company")
    membership_id, membership_company_id = authorized
    return AuthenticatedCompanyContext(
        user_id=user_id,
        company_id=membership_company_id,
        membership_id=membership_id,
        identity_subject=identity_subject,
    )
