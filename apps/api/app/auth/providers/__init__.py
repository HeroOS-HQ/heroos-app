from app.auth.exceptions import AuthenticationConfigurationError
from app.auth.providers.base import AuthenticationProvider
from app.auth.providers.cognito import CognitoAccessTokenProvider, build_jwks_client
from app.auth.providers.development import DevelopmentAuthenticationProvider
from app.core.config import Settings

__all__ = [
    "AuthenticationProvider",
    "build_authentication_provider",
]


def build_authentication_provider(settings: Settings) -> AuthenticationProvider | None:
    """Build the configured provider, or ``None`` when none is configured.

    ``None`` is fail-closed: protected routes then reject every request.
    """
    match settings.heroos_auth_provider:
        case None:
            return None
        case "development":
            if settings.heroos_dev_auth_secret is None:
                raise AuthenticationConfigurationError("HEROOS_DEV_AUTH_SECRET is required")
            return DevelopmentAuthenticationProvider(
                environment=settings.heroos_env,
                secret=settings.heroos_dev_auth_secret,
            )
        case "cognito":
            issuer = settings.heroos_cognito_issuer
            app_client_id = settings.heroos_cognito_app_client_id
            jwks_uri = settings.cognito_jwks_uri
            if not issuer or not app_client_id or not jwks_uri:
                raise AuthenticationConfigurationError("Cognito configuration is incomplete")
            return CognitoAccessTokenProvider(
                issuer=issuer,
                app_client_id=app_client_id,
                jwks_client=build_jwks_client(jwks_uri),
                resource_audience=settings.heroos_cognito_resource_audience,
            )
