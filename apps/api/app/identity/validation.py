"""Input validation for identity provisioning.

Issuers and subjects are bound exactly as a provider will present them, so they
are validated, never normalized: a value with stray whitespace is refused rather
than silently trimmed into a different identity.
"""

import re
from typing import Final

from app.db.models.user_identity import MAX_ISSUER_LENGTH, MAX_SUBJECT_LENGTH
from app.identity.errors import INVALID_INPUT, IdentityOperationError

# https issuers (Auth0, Cognito, any OpenID Provider) or HeroOS URNs (local
# development and tests). No whitespace, quotes, query or fragment. Kept equal to
# the B1a migration's ISSUER_PATTERN.
_ISSUER: Final = re.compile(r"https://[^\s?#'\"\\]+|urn:heroos:[a-z0-9:-]+")
# A change reference: an issue key such as HER-230. Never free text, so it
# cannot carry personal data. The database trigger enforces the same format.
ACTOR_REFERENCE: Final = re.compile(r"[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}")


def validate_issuer(issuer: str) -> str:
    if (
        not isinstance(issuer, str)
        or len(issuer) > MAX_ISSUER_LENGTH
        or not _ISSUER.fullmatch(issuer)
    ):
        raise IdentityOperationError(INVALID_INPUT)
    return issuer


def validate_subject(subject: str) -> str:
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > MAX_SUBJECT_LENGTH
        or subject != subject.strip()
        or not subject.isprintable()
    ):
        raise IdentityOperationError(INVALID_INPUT)
    return subject


def validate_actor_reference(reference: str) -> str:
    if not isinstance(reference, str) or not ACTOR_REFERENCE.fullmatch(reference):
        raise IdentityOperationError(INVALID_INPUT)
    return reference
