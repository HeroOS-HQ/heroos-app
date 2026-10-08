"""HeroOS authorization: verified identity -> User -> Company Membership.

Authorization comes only from HeroOS data. A requested ``company_id`` is a
resource identifier; it grants nothing until a Membership row for this User and
that Company is found server-side.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError
from app.auth.models import AuthenticatedCompanyContext, VerifiedIdentity
from app.db.models import Membership, User
from app.tenancy.context import TenantContextError, set_tenant_context


def resolve_user(db: Session, identity: VerifiedIdentity) -> User:
    """Map a verified identity to its HeroOS User by ``identity_subject``.

    No just-in-time provisioning: an identity without a User row is denied.
    """
    user = db.scalar(select(User).where(User.identity_subject == identity.subject))
    if user is None:
        raise AuthorizationError("no HeroOS user for verified identity")
    return user


def authorize_company(db: Session, user: User, company_id: UUID) -> AuthenticatedCompanyContext:
    """Authorize ``user`` for ``company_id`` through an existing Membership.

    ``memberships`` is protected by Row-Level Security, so the lookup runs with the
    *requested* Company as a candidate tenant scope. That scope is not
    authorization: it only lets this one query see the requested Company's
    Membership rows, and the query is further restricted to this User. Only an
    existing Membership authorizes.

    The candidate scope never outlives the lookup: the transaction is rolled back
    before returning, on success and failure alike. Call this before any writes
    on ``db``. Tenant data access then opens a new transaction scoped from the
    returned context (``app.tenancy.open_company_scope``).
    """
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
        # e.g. the nil UUID: the same generic denial as any unknown Company.
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
