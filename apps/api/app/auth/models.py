from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """An external identity whose credential has been cryptographically verified.

    Authentication output only: it carries no HeroOS User or Company access.
    ``(issuer, subject)`` is matched exactly against ``user_identities``.
    """

    subject: str
    issuer: str


@dataclass(frozen=True, slots=True)
class ResolvedUser:
    """An active HeroOS User reached through an active identity binding.

    Carries internal IDs only; never the external subject.
    """

    user_id: UUID
    identity_id: UUID


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
    identity_id: UUID
