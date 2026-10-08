class AuthenticationError(Exception):
    """The credential is missing, malformed or failed verification (HTTP 401).

    ``reason`` is a fixed internal description for server-side logs. It must never
    contain the credential and is never returned to the caller.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AuthorizationError(Exception):
    """The identity is verified but HeroOS grants no access (HTTP 403).

    ``reason`` is for server-side logs only; callers receive a generic denial so
    they cannot tell an unknown User from a missing Membership.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AuthenticationConfigurationError(RuntimeError):
    """Authentication configuration is unsafe or incomplete; startup must stop."""
