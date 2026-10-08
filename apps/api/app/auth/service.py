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


def resolve_user(db: Session, identity: VerifiedIdentity) -> User:
    """Map a verified identity to its HeroOS User by ``identity_subject``.

    No just-in-time provisioning: an identity without a User row is denied.
    """
    user = db.scalar(select(User).where(User.identity_subject == identity.subject))
    if user is None:
        raise AuthorizationError("no HeroOS user for verified identity")
    return user


def authorize_company(db: Session, user: User, company_id: UUID) -> AuthenticatedCompanyContext:
    """Authorize ``user`` for ``company_id`` through an existing Membership."""
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.company_id == company_id,
        )
    )
    if membership is None:
        raise AuthorizationError("no membership for requested company")
    return AuthenticatedCompanyContext(
        user_id=user.id,
        company_id=membership.company_id,
        membership_id=membership.id,
        identity_subject=user.identity_subject,
    )
