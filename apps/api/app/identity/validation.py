"""Input validation for identity provisioning and Company registration.

Issuers and subjects are bound exactly as a provider will present them, so they
are validated, never normalized: a value with stray whitespace is refused rather
than silently trimmed into a different identity. Company names and licensing
authorities follow the same rule.
"""

import re
from typing import Final

from app.db.models.company_blueprint import MAX_LICENSING_AUTHORITY_LENGTH
from app.db.models.user_identity import MAX_ISSUER_LENGTH, MAX_SUBJECT_LENGTH
from app.identity.errors import INVALID_INPUT, IdentityOperationError

# companies.name is VARCHAR(200).
MAX_COMPANY_NAME_LENGTH: Final = 200

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


def _validate_text(value: str, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_length
        or value != value.strip()
        or not value.isprintable()
    ):
        raise IdentityOperationError(INVALID_INPUT)
    return value


def validate_company_name(name: str) -> str:
    """A Company's display name: refused, never trimmed, if it is untidy."""
    return _validate_text(name, MAX_COMPANY_NAME_LENGTH)


def validate_licensing_authority(authority: str) -> str:
    return _validate_text(authority, MAX_LICENSING_AUTHORITY_LENGTH)


def validate_choice(value: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise IdentityOperationError(INVALID_INPUT)
    return value
