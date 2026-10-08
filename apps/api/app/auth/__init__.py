"""Authentication (who is calling) and Company authorization (what they may access).

See docs/architecture/authentication.md.
"""

from app.auth.exceptions import (
    AuthenticationConfigurationError,
    AuthenticationError,
    AuthorizationError,
)
from app.auth.models import AuthenticatedCompanyContext, VerifiedIdentity

__all__ = [
    "AuthenticatedCompanyContext",
    "AuthenticationConfigurationError",
    "AuthenticationError",
    "AuthorizationError",
    "VerifiedIdentity",
]
