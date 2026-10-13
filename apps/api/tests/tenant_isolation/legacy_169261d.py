"""Frozen copy of the database-facing code of the M1-10B API.

Source: ``169261dc437e8d22fc4c77bc3c4098495268b4b3`` (M1-10B merged, before
M1-10C): the ``TimestampMixin`` of ``app/db/base.py``, the models in
``app/db/models/{company,user,user_identity,membership,case}.py``,
``resolve_user`` / ``authorize_company`` from ``app/auth/service.py``,
``open_company_scope`` and ``list_cases``. Copied verbatim except for import
paths, an own declarative base, docstrings, and the omission of foreign keys
and constraints that only matter for DDL (they do not change the SQL an
authorization or a read sends). ``app.tenancy.context`` is unchanged since
that revision and is imported as is.

Used only by ``test_identity_migration.py`` and ``test_company_migration.py``
to prove what the M1-10B API does on the B1a, B1b and C1 schemas (it has no
``memberships.role``). Do not modify: it is evidence, not code to maintain.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.tenancy.context import TenantContextError, set_tenant_context

MEMBERSHIP_ACTIVE: Final = "active"
USER_ACTIVE: Final = "active"
IDENTITY_ACTIVE: Final = "active"


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


class UserIdentity(TimestampMixin, Base):
    __tablename__ = "user_identities"

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

    issuer: Mapped[str] = mapped_column(String(512), nullable=False)

    subject: Mapped[str] = mapped_column(String(255), nullable=False)

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


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"

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


class Case(TimestampMixin, Base):
    __tablename__ = "cases"

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


class AuthorizationError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    subject: str
    issuer: str


@dataclass(frozen=True, slots=True)
class ResolvedUser:
    user_id: UUID
    identity_id: UUID


@dataclass(frozen=True, slots=True)
class AuthenticatedCompanyContext:
    user_id: UUID
    company_id: UUID
    membership_id: UUID
    identity_id: UUID


def resolve_user(db: Session, identity: VerifiedIdentity) -> ResolvedUser:
    row = db.execute(
        select(UserIdentity.user_id, UserIdentity.id)
        .join(User, User.id == UserIdentity.user_id)
        .where(
            UserIdentity.issuer == identity.issuer,
            UserIdentity.subject == identity.subject,
            UserIdentity.status == IDENTITY_ACTIVE,
            User.status == USER_ACTIVE,
        )
    ).one_or_none()
    if row is None:
        raise AuthorizationError("no active HeroOS user for verified identity")
    return ResolvedUser(user_id=row.user_id, identity_id=row.id)


def authorize_company(
    db: Session, user: ResolvedUser, company_id: UUID
) -> AuthenticatedCompanyContext:
    try:
        set_tenant_context(db, company_id)
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.user_id,
                Membership.company_id == company_id,
                Membership.status == MEMBERSHIP_ACTIVE,
            )
        )
        authorized = None if membership is None else (membership.id, membership.company_id)
    except TenantContextError:
        raise AuthorizationError("invalid requested company") from None
    finally:
        db.rollback()

    if authorized is None:
        raise AuthorizationError("no active membership for requested company")
    membership_id, membership_company_id = authorized
    return AuthenticatedCompanyContext(
        user_id=user.user_id,
        company_id=membership_company_id,
        membership_id=membership_id,
        identity_id=user.identity_id,
    )


def get_company(db: Session, context: AuthenticatedCompanyContext) -> Company | None:
    """``GET /companies/{id}``: ``open_company_scope`` + ``companies.get_company``."""
    set_tenant_context(db, context.company_id)
    return db.scalar(select(Company).where(Company.id == context.company_id))


def list_cases(db: Session, context: AuthenticatedCompanyContext) -> Sequence[Case]:
    """``GET /companies/{id}/cases``: ``open_company_scope`` + ``cases.list_cases``."""
    set_tenant_context(db, context.company_id)
    return db.scalars(
        select(Case).where(Case.company_id == context.company_id).order_by(Case.created_at, Case.id)
    ).all()
