"""Amazon Cognito access-token verification.

HeroOS accepts Cognito **access** tokens for API calls (see
docs/architecture/authentication.md). Validation:

- RS256 signature against the User Pool JWKS, key selected by ``kid``
- ``iss`` equals the configured User Pool issuer
- ``exp`` / ``iat`` present and ``exp`` not passed
- ``token_use == "access"``
- ``client_id`` equals the configured App Client ID (access tokens carry no
  ``aud``; a token that does carry ``aud``, such as an ID token, is rejected)
- non-empty ``sub``, the stable identity mapped to ``users.identity_subject``

No Cognito resource exists yet; live activation is M3 work.
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
    def __init__(self, *, issuer: str, app_client_id: str, jwks_client: jwt.PyJWKClient) -> None:
        self._issuer = issuer
        self._app_client_id = app_client_id
        self._jwks_client = jwks_client

    def authenticate(self, token: str) -> VerifiedIdentity:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=[COGNITO_ALGORITHM],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "sub", "token_use", "client_id"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"cognito token rejected ({type(exc).__name__})") from None

        if claims["token_use"] != COGNITO_ACCESS_TOKEN_USE:
            raise AuthenticationError("cognito token_use is not 'access'")
        if claims["client_id"] != self._app_client_id:
            raise AuthenticationError("cognito client_id does not match the App Client")

        return VerifiedIdentity(subject=require_subject(claims), issuer=self._issuer)
