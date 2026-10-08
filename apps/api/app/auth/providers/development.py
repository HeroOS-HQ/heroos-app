"""Local development authentication provider.

A real signature-verifying provider, not an auth bypass: requests still need a
Bearer JWT signed with ``HEROOS_DEV_AUTH_SECRET``. It refuses to exist outside
``HEROOS_ENV=development``. The token proves identity only; Company access still
requires a HeroOS User and Membership.
"""

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import SecretStr

from app.auth.exceptions import AuthenticationConfigurationError, AuthenticationError
from app.auth.models import VerifiedIdentity
from app.auth.providers.base import require_subject
from app.core.config import DEV_AUTH_SECRET_MIN_LENGTH, Environment

DEVELOPMENT_ISSUER = "urn:heroos:local-development"
DEVELOPMENT_ALGORITHM = "HS256"
DEFAULT_DEVELOPMENT_TOKEN_LIFETIME = timedelta(minutes=15)
MAX_DEVELOPMENT_TOKEN_LIFETIME = timedelta(hours=1)


def _require_development(environment: Environment, secret: SecretStr) -> None:
    if environment != "development":
        raise AuthenticationConfigurationError(
            "The development authentication provider is only allowed when HEROOS_ENV=development"
        )
    if len(secret.get_secret_value()) < DEV_AUTH_SECRET_MIN_LENGTH:
        raise AuthenticationConfigurationError("HEROOS_DEV_AUTH_SECRET is too short")


class DevelopmentAuthenticationProvider:
    def __init__(self, *, environment: Environment, secret: SecretStr) -> None:
        # Re-checked here, independent of Settings validation, so the provider
        # cannot be constructed for a deployed environment by any path.
        _require_development(environment, secret)
        self._secret = secret

    def authenticate(self, token: str) -> VerifiedIdentity:
        try:
            claims = jwt.decode(
                token,
                self._secret.get_secret_value(),
                algorithms=[DEVELOPMENT_ALGORITHM],
                issuer=DEVELOPMENT_ISSUER,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(
                f"development token rejected ({type(exc).__name__})"
            ) from None

        lifetime = claims["exp"] - claims["iat"]
        if lifetime > MAX_DEVELOPMENT_TOKEN_LIFETIME.total_seconds():
            raise AuthenticationError("development token lifetime exceeds the maximum")

        return VerifiedIdentity(subject=require_subject(claims), issuer=DEVELOPMENT_ISSUER)


def issue_development_token(
    *,
    environment: Environment,
    secret: SecretStr,
    subject: str,
    lifetime: timedelta = DEFAULT_DEVELOPMENT_TOKEN_LIFETIME,
    now: datetime | None = None,
) -> str:
    """Issue a short-lived development bearer token for ``subject``.

    Produces an authentication credential only. It creates no User or Membership
    and grants no Company access.
    """
    _require_development(environment, secret)
    if lifetime <= timedelta(0) or lifetime > MAX_DEVELOPMENT_TOKEN_LIFETIME:
        raise ValueError(f"lifetime must be positive and at most {MAX_DEVELOPMENT_TOKEN_LIFETIME}")
    require_subject({"sub": subject})

    issued_at = now or datetime.now(UTC)
    claims = {
        "iss": DEVELOPMENT_ISSUER,
        "sub": subject,
        "iat": issued_at,
        "exp": issued_at + lifetime,
    }
    return jwt.encode(claims, secret.get_secret_value(), algorithm=DEVELOPMENT_ALGORITHM)
