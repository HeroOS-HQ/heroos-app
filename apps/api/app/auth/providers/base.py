from collections.abc import Mapping
from typing import Any, Protocol

from app.auth.exceptions import AuthenticationError
from app.auth.models import VerifiedIdentity

# Matches the ``user_identities.subject`` column length.
MAX_SUBJECT_LENGTH = 255


class AuthenticationProvider(Protocol):
    """Verifies a bearer credential and returns the identity it proves.

    Providers only authenticate. They must not consult Users or Memberships, and
    must raise ``AuthenticationError`` for every invalid credential.
    """

    def authenticate(self, token: str) -> VerifiedIdentity: ...


def require_subject(claims: Mapping[str, Any]) -> str:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationError("token subject is missing or empty")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise AuthenticationError("token subject is too long")
    return subject
