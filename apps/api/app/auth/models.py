from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """An external identity whose credential has been cryptographically verified.

    Authentication output only: it carries no HeroOS User or Company access.
    """

    # Stable external subject; maps to ``users.identity_subject``.
    subject: str
    issuer: str


@dataclass(frozen=True, slots=True)
class AuthenticatedCompanyContext:
    """Trusted request context for one Company.

    Only constructed after credential verification, HeroOS User resolution and a
    server-side Membership lookup. ``company_id`` comes from the Membership row,
    never from client input.
    """

    user_id: UUID
    company_id: UUID
    membership_id: UUID
    identity_subject: str
