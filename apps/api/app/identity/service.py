"""Identity, lifecycle and Membership operations for platform operators (ADR-008).

Each function performs one operation inside the caller's transaction and never
commits. The caller (the operator CLI) sets the change reference first
(``app.identity.operator.set_actor_reference``) and commits once, so the change
and its trigger-written audit event succeed or fail together.

Every operation is idempotent: repeating it reports ``unchanged`` and writes
nothing. Conflicts are refused with a fixed code, never resolved silently. There
is no deletion (PRIV-008, PRIV-020); suspension and revocation keep every row.
Company registration and jurisdiction confirmation are in
``app.identity.companies`` (M1-10C).

The database enforces the same boundaries for the operator role: column-level
grants (bindings are immutable), RLS for Membership changes (one Company per
transaction), and no access to HR data.
"""

from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Membership, User, UserIdentity
from app.db.models.membership import MEMBERSHIP_ACTIVE, MEMBERSHIP_REVOKED, MEMBERSHIP_ROLES
from app.db.models.user import USER_ACTIVE, USER_SUSPENDED
from app.db.models.user_identity import IDENTITY_ACTIVE, IDENTITY_REVOKED
from app.identity import errors
from app.identity.errors import IdentityOperationError
from app.identity.operator import open_operator_company_scope
from app.identity.validation import validate_choice, validate_issuer, validate_subject

CREATED: Final = "created"
UPDATED: Final = "updated"
UNCHANGED: Final = "unchanged"


@dataclass(frozen=True)
class OperationResult:
    """Outcome plus internal IDs only (never an issuer or subject).

    ``details`` carries non-identifying codes (for example a role or a
    jurisdiction readiness), never personal data.
    """

    outcome: str
    ids: dict[str, UUID] = field(default_factory=dict)
    details: dict[str, str | None] = field(default_factory=dict)


# --- lookups -----------------------------------------------------------------


def _identity_by_key(session: Session, issuer: str, subject: str) -> UserIdentity | None:
    return session.scalar(
        select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.subject == subject)
    )


def _active_identity_for_issuer(
    session: Session, user_id: UUID, issuer: str, *, excluding: UUID | None = None
) -> UserIdentity | None:
    query = select(UserIdentity).where(
        UserIdentity.user_id == user_id,
        UserIdentity.issuer == issuer,
        UserIdentity.status == IDENTITY_ACTIVE,
    )
    if excluding is not None:
        query = query.where(UserIdentity.id != excluding)
    return session.scalar(query)


def _require_user(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise IdentityOperationError(errors.USER_NOT_FOUND)
    return user


def _require_active_user(session: Session, user_id: UUID) -> User:
    user = _require_user(session, user_id)
    if user.status != USER_ACTIVE:
        raise IdentityOperationError(errors.USER_SUSPENDED)
    return user


def _membership_for_user(session: Session, company_id: UUID, user_id: UUID) -> Membership | None:
    return session.scalar(
        select(Membership).where(Membership.company_id == company_id, Membership.user_id == user_id)
    )


def _membership_by_id(session: Session, company_id: UUID, membership_id: UUID) -> Membership:
    membership = session.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.id == membership_id
        )
    )
    if membership is None:
        # Another Company's Membership is invisible under RLS: same answer.
        raise IdentityOperationError(errors.MEMBERSHIP_NOT_FOUND)
    return membership


def _require_active_binding(session: Session, issuer: str, subject: str) -> UserIdentity:
    identity = _identity_by_key(session, validate_issuer(issuer), validate_subject(subject))
    if identity is None:
        raise IdentityOperationError(errors.IDENTITY_NOT_FOUND)
    if identity.status != IDENTITY_ACTIVE:
        raise IdentityOperationError(errors.IDENTITY_REVOKED)
    _require_active_user(session, identity.user_id)
    return identity


# --- provisioning --------------------------------------------------------------


def provision_member(
    session: Session, *, company_id: UUID, issuer: str, subject: str
) -> OperationResult:
    """Create a User, bind the external identity and grant one Company Membership.

    For a person who does not exist in HeroOS yet. If the identity is already
    bound, this is ``unchanged`` only when it already has an active Membership
    of this Company; otherwise the operator must use ``grant_membership``, so a
    typo can never silently merge two people.
    """
    issuer = validate_issuer(issuer)
    subject = validate_subject(subject)
    open_operator_company_scope(session, company_id)

    existing = _identity_by_key(session, issuer, subject)
    if existing is not None:
        membership = _membership_for_user(session, company_id, existing.user_id)
        user = _require_user(session, existing.user_id)
        if (
            membership is not None
            and membership.status == MEMBERSHIP_ACTIVE
            and existing.status == IDENTITY_ACTIVE
            and user.status == USER_ACTIVE
        ):
            return OperationResult(
                UNCHANGED,
                {
                    "user_id": existing.user_id,
                    "identity_id": existing.id,
                    "membership_id": membership.id,
                },
            )
        raise IdentityOperationError(errors.IDENTITY_EXISTS)

    user = User()
    session.add(user)
    session.flush()
    identity = UserIdentity(user_id=user.id, issuer=issuer, subject=subject)
    membership = Membership(company_id=company_id, user_id=user.id)
    session.add_all([identity, membership])
    session.flush()
    return OperationResult(
        CREATED,
        {"user_id": user.id, "identity_id": identity.id, "membership_id": membership.id},
    )


def grant_membership(
    session: Session, *, company_id: UUID, issuer: str, subject: str
) -> OperationResult:
    """Give an existing, active User (found by an active binding) access to a Company."""
    open_operator_company_scope(session, company_id)
    identity = _require_active_binding(session, issuer, subject)

    membership = _membership_for_user(session, company_id, identity.user_id)
    if membership is not None:
        if membership.status == MEMBERSHIP_REVOKED:
            raise IdentityOperationError(errors.MEMBERSHIP_REVOKED)
        return OperationResult(
            UNCHANGED, {"user_id": identity.user_id, "membership_id": membership.id}
        )
    membership = Membership(company_id=company_id, user_id=identity.user_id)
    session.add(membership)
    session.flush()
    return OperationResult(CREATED, {"user_id": identity.user_id, "membership_id": membership.id})


def revoke_membership(
    session: Session, *, company_id: UUID, membership_id: UUID
) -> OperationResult:
    open_operator_company_scope(session, company_id)
    membership = _membership_by_id(session, company_id, membership_id)
    if membership.status == MEMBERSHIP_REVOKED:
        return OperationResult(UNCHANGED, {"membership_id": membership.id})
    membership.status = MEMBERSHIP_REVOKED
    membership.revoked_at = func.now()
    session.flush()
    return OperationResult(UPDATED, {"membership_id": membership.id})


def reactivate_membership(
    session: Session, *, company_id: UUID, membership_id: UUID
) -> OperationResult:
    open_operator_company_scope(session, company_id)
    membership = _membership_by_id(session, company_id, membership_id)
    if membership.status == MEMBERSHIP_ACTIVE:
        return OperationResult(UNCHANGED, {"membership_id": membership.id})
    _require_active_user(session, membership.user_id)
    membership.status = MEMBERSHIP_ACTIVE
    membership.revoked_at = None
    session.flush()
    return OperationResult(UPDATED, {"membership_id": membership.id})


def set_membership_role(
    session: Session, *, company_id: UUID, membership_id: UUID, role: str
) -> OperationResult:
    """Make an existing Membership ``company_admin`` or ``member`` (M1-10C).

    The trusted way to appoint or remove Company administrators, including for
    Companies that existed before roles did. One Company per transaction under
    RLS; audited as ``membership_role_changed``. A revoked Membership is
    reactivated first, so a role change never silently restores access.
    """
    role = validate_choice(role, MEMBERSHIP_ROLES)
    open_operator_company_scope(session, company_id)
    membership = _membership_by_id(session, company_id, membership_id)
    if membership.status == MEMBERSHIP_REVOKED:
        raise IdentityOperationError(errors.MEMBERSHIP_REVOKED)
    result_ids = {"membership_id": membership.id, "user_id": membership.user_id}
    if membership.role == role:
        return OperationResult(UNCHANGED, result_ids, {"role": role})
    membership.role = role
    session.flush()
    return OperationResult(UPDATED, result_ids, {"role": role})


# --- identity bindings -----------------------------------------------------------


def bind_identity(session: Session, *, user_id: UUID, issuer: str, subject: str) -> OperationResult:
    """Bind an additional external identity (e.g. Cognito at M5) to an existing User."""
    issuer = validate_issuer(issuer)
    subject = validate_subject(subject)
    _require_active_user(session, user_id)

    existing = _identity_by_key(session, issuer, subject)
    if existing is not None:
        if existing.user_id == user_id and existing.status == IDENTITY_ACTIVE:
            return OperationResult(UNCHANGED, {"user_id": user_id, "identity_id": existing.id})
        # Bound to someone else, or revoked: a binding is never reassigned.
        raise IdentityOperationError(errors.IDENTITY_CONFLICT)
    if _active_identity_for_issuer(session, user_id, issuer) is not None:
        raise IdentityOperationError(errors.ACTIVE_IDENTITY_EXISTS_FOR_ISSUER)

    identity = UserIdentity(user_id=user_id, issuer=issuer, subject=subject)
    session.add(identity)
    session.flush()
    return OperationResult(CREATED, {"user_id": user_id, "identity_id": identity.id})


def _require_identity(session: Session, identity_id: UUID) -> UserIdentity:
    identity = session.get(UserIdentity, identity_id)
    if identity is None:
        raise IdentityOperationError(errors.IDENTITY_NOT_FOUND)
    return identity


def revoke_identity(session: Session, *, identity_id: UUID) -> OperationResult:
    identity = _require_identity(session, identity_id)
    if identity.status == IDENTITY_REVOKED:
        return OperationResult(UNCHANGED, {"identity_id": identity.id})
    identity.status = IDENTITY_REVOKED
    identity.revoked_at = func.now()
    session.flush()
    return OperationResult(UPDATED, {"identity_id": identity.id})


def reactivate_identity(session: Session, *, identity_id: UUID) -> OperationResult:
    """Re-enable a revoked binding (same row; never another User's)."""
    identity = _require_identity(session, identity_id)
    if identity.status == IDENTITY_ACTIVE:
        return OperationResult(UNCHANGED, {"identity_id": identity.id})
    if (
        _active_identity_for_issuer(
            session, identity.user_id, identity.issuer, excluding=identity.id
        )
        is not None
    ):
        raise IdentityOperationError(errors.ACTIVE_IDENTITY_EXISTS_FOR_ISSUER)
    identity.status = IDENTITY_ACTIVE
    identity.revoked_at = None
    session.flush()
    return OperationResult(UPDATED, {"identity_id": identity.id})


# --- users -------------------------------------------------------------------------


def suspend_user(session: Session, *, user_id: UUID) -> OperationResult:
    """Deny the User everywhere, on the next request. Not deletion."""
    user = _require_user(session, user_id)
    if user.status == USER_SUSPENDED:
        return OperationResult(UNCHANGED, {"user_id": user.id})
    user.status = USER_SUSPENDED
    user.suspended_at = func.now()
    session.flush()
    return OperationResult(UPDATED, {"user_id": user.id})


def reactivate_user(session: Session, *, user_id: UUID) -> OperationResult:
    user = _require_user(session, user_id)
    if user.status == USER_ACTIVE:
        return OperationResult(UNCHANGED, {"user_id": user.id})
    user.status = USER_ACTIVE
    user.suspended_at = None
    session.flush()
    return OperationResult(UPDATED, {"user_id": user.id})
