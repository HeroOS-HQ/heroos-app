from typing import Final

# Fixed result codes. Messages never contain issuers, subjects or credentials.
INVALID_INPUT: Final = "invalid_input"
COMPANY_NOT_FOUND: Final = "company_not_found"
USER_NOT_FOUND: Final = "user_not_found"
IDENTITY_NOT_FOUND: Final = "identity_not_found"
MEMBERSHIP_NOT_FOUND: Final = "membership_not_found"
IDENTITY_CONFLICT: Final = "identity_conflict"
IDENTITY_EXISTS: Final = "identity_exists_use_grant"
ACTIVE_IDENTITY_EXISTS_FOR_ISSUER: Final = "active_identity_exists_for_issuer"
IDENTITY_REVOKED: Final = "identity_revoked"
USER_SUSPENDED: Final = "user_suspended"
MEMBERSHIP_REVOKED: Final = "membership_revoked_use_reactivate"


class IdentityOperationError(Exception):
    """An identity operation was refused. ``code`` is one of the fixed codes above."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
