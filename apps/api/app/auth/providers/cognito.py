"""Amazon Cognito access-token verification.

HeroOS accepts Cognito **access** tokens for API calls (see
docs/architecture/authentication.md). Validation:

- RS256 signature against the User Pool JWKS, key selected by ``kid``
- ``iss`` equals the configured User Pool issuer
- ``exp`` / ``iat`` present and ``exp`` not passed
- ``token_use == "access"``
- ``client_id`` equals the configured App Client ID
- ``aud`` only when a resource audience is configured: it must then be present
  and match. Otherwise ``aud`` is ignored; it is never used to tell access
  tokens from ID tokens (``token_use`` does that), because resource-bound
  access tokens legitimately carry ``aud``
- non-empty ``sub``; ``(issuer, sub)`` is matched exactly in ``user_identities``

No Cognito resource exists yet; live activation is outside this code (see
docs/architecture/authentication.md).
"""

import jwt

from app.auth.exceptions import AuthenticationError
from app.auth.models import VerifiedIdentity
from app.auth.providers.base import require_subject

COGNITO_ALGORITHM = "RS256"
COGNITO_ACCESS_TOKEN_USE = "access"
JWKS_CACHE_LIFESPAN_SECONDS = 3600
JWKS_FETCH_TIMEOUT_SECONDS = 5


def build_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    # Keys are fetched lazily on first use, so startup never contacts AWS.
    return jwt.PyJWKClient(
        jwks_uri,
        cache_keys=True,
        lifespan=JWKS_CACHE_LIFESPAN_SECONDS,
        timeout=JWKS_FETCH_TIMEOUT_SECONDS,
    )


class CognitoAccessTokenProvider:
    def __init__(
        self,
        *,
        issuer: str,
        app_client_id: str,
        jwks_client: jwt.PyJWKClient,
        resource_audience: str | None = None,
    ) -> None:
        self._issuer = issuer
        self._app_client_id = app_client_id
        self._jwks_client = jwks_client
        self._resource_audience = resource_audience

    def authenticate(self, token: str) -> VerifiedIdentity:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[COGNITO_ALGORITHM],
                issuer=self._issuer,
                # With an audience, PyJWT requires `aud` and checks it matches.
                audience=self._resource_audience,
                options={
                    "require": ["exp", "iat", "iss", "sub", "token_use", "client_id"],
                    "verify_aud": self._resource_audience is not None,
                },
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"cognito token rejected ({type(exc).__name__})") from None

        if claims["token_use"] != COGNITO_ACCESS_TOKEN_USE:
            raise AuthenticationError("cognito token_use is not 'access'")
        if claims["client_id"] != self._app_client_id:
            raise AuthenticationError("cognito client_id does not match the App Client")

        return VerifiedIdentity(subject=require_subject(claims), issuer=self._issuer)
