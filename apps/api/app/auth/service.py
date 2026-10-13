"""HeroOS authorization: verified identity -> User -> Company Membership.

Authorization comes only from HeroOS data. A requested ``company_id`` is a
resource identifier; it grants nothing until a Membership row for this User and
that Company is found server-side.

Lifecycle (ADR-008) is checked here *and* by Row-Level Security for the API
role: revoked identities, suspended Users and revoked Memberships are filtered
in these queries and are also invisible to ``heroos_app_runtime``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext, ResolvedUser, VerifiedIdentity
from app.db.models import Membership, User, UserIdentity
from app.db.models.membership import MEMBERSHIP_ACTIVE
from app.db.models.user import USER_ACTIVE
from app.db.models.user_identity import IDENTITY_ACTIVE
from app.tenancy.context import TenantContextError, set_tenant_context


def resolve_user(db: Session, identity: VerifiedIdentity) -> ResolvedUser:
    """Map a verified identity to its active HeroOS User.

    Exact ``(issuer, subject)`` match on an active binding of an active User.
    Never by email or any other claim. No just-in-time provisioning: an unknown,
    revoked or suspended identity is denied with the same error.
    """
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
    """Authorize ``user`` for ``company_id`` through an active Membership.

    ``memberships`` is protected by Row-Level Security, so the lookup runs with the
    *requested* Company as a candidate tenant scope. That scope is not
    authorization: it only lets this one query see the requested Company's
    Membership rows, and the query is further restricted to this User. Only an
    existing, active Membership authorizes.

    The candidate scope never outlives the lookup: the transaction is rolled back
    before returning, on success and failure alike. Call this before any writes
    on ``db``. Tenant data access then opens a new transaction scoped from the
    returned context (``app.tenancy.open_company_scope``).
    """
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
        # e.g. the nil UUID: the same generic denial as any unknown Company.
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
