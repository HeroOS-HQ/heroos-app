from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator

from app.core.database_settings import DatabaseSettings

Environment = Literal["development", "staging", "production"]
AuthProviderName = Literal["development", "cognito"]
# "s3" is the M3 production contract; no adapter exists yet, so selecting it
# stops startup instead of falling back to anything else.
StorageProviderName = Literal["local", "s3"]

# HS256 keys shorter than the 256-bit digest weaken the development signature.
DEV_AUTH_SECRET_MIN_LENGTH = 32


class Settings(DatabaseSettings):
    """Full API configuration: database plus environment and authentication."""

    # Required, no default: a missing HEROOS_ENV must stop startup rather than
    # silently selecting development.
    heroos_env: Environment

    # Authentication. See docs/architecture/authentication.md.
    # Unset means no provider: protected routes reject every request.
    heroos_auth_provider: AuthProviderName | None = None
    heroos_dev_auth_secret: SecretStr | None = None
    heroos_cognito_issuer: str | None = None
    heroos_cognito_app_client_id: str | None = None
    heroos_cognito_jwks_uri: str | None = None
    # Optional resource-server audience. When set, access tokens must carry a
    # matching `aud`; when unset, `aud` is not used for any decision.
    heroos_cognito_resource_audience: str | None = None

    # Private object storage. See docs/architecture/private-object-storage.md.
    # Unset means no storage: every storage operation fails; nothing falls back
    # to local disk.
    heroos_storage_provider: StorageProviderName | None = None
    heroos_local_storage_root: Path | None = None

    @model_validator(mode="after")
    def _validate_storage(self) -> Self:
        if self.heroos_env != "development":
            # Deployed environments never store private objects on local disk.
            if self.heroos_storage_provider == "local":
                raise ValueError(
                    "HEROOS_STORAGE_PROVIDER=local is not allowed when "
                    f"HEROOS_ENV={self.heroos_env}"
                )
            if self.heroos_local_storage_root is not None:
                raise ValueError("HEROOS_LOCAL_STORAGE_ROOT must not be set outside development")

        if self.heroos_storage_provider == "local":
            root = self.heroos_local_storage_root
            if root is None or not root.is_absolute():
                raise ValueError(
                    "HEROOS_LOCAL_STORAGE_ROOT must be an absolute path for the local provider"
                )
        elif self.heroos_local_storage_root is not None:
            raise ValueError("HEROOS_LOCAL_STORAGE_ROOT is only valid with the local provider")

        return self

    @model_validator(mode="after")
    def _validate_authentication(self) -> Self:
        if self.heroos_env != "development":
            # Deployed environments fail closed: Cognito only, and no development
            # signing material may be present at all.
            if self.heroos_auth_provider != "cognito":
                raise ValueError(
                    f"HEROOS_AUTH_PROVIDER must be 'cognito' when HEROOS_ENV={self.heroos_env}"
                )
            if self.heroos_dev_auth_secret is not None:
                raise ValueError("HEROOS_DEV_AUTH_SECRET must not be set outside development")

        if self.heroos_auth_provider == "development":
            secret = self.heroos_dev_auth_secret
            if secret is None or len(secret.get_secret_value()) < DEV_AUTH_SECRET_MIN_LENGTH:
                raise ValueError(
                    "HEROOS_DEV_AUTH_SECRET must be at least "
                    f"{DEV_AUTH_SECRET_MIN_LENGTH} characters for the development provider"
                )

        if self.heroos_auth_provider == "cognito":
            if not self.heroos_cognito_issuer or not self.heroos_cognito_app_client_id:
                raise ValueError(
                    "HEROOS_COGNITO_ISSUER and HEROOS_COGNITO_APP_CLIENT_ID are required "
                    "for the cognito provider"
                )
            issuer = self.heroos_cognito_issuer
            if not issuer.startswith("https://") or issuer.endswith("/"):
                # Compared verbatim with the token `iss` claim, which has no
                # trailing slash.
                raise ValueError("HEROOS_COGNITO_ISSUER must be an https URL without a trailing /")
            if self.heroos_cognito_jwks_uri and not self.heroos_cognito_jwks_uri.startswith(
                "https://"
            ):
                raise ValueError("HEROOS_COGNITO_JWKS_URI must be an https URL")
            audience = self.heroos_cognito_resource_audience
            if audience is not None and not audience.strip():
                raise ValueError("HEROOS_COGNITO_RESOURCE_AUDIENCE must not be blank when set")

        return self

    @property
    def cognito_jwks_uri(self) -> str | None:
        if self.heroos_cognito_jwks_uri:
            return self.heroos_cognito_jwks_uri
        if self.heroos_cognito_issuer:
            return f"{self.heroos_cognito_issuer}/.well-known/jwks.json"
        return None


# Required fields come from the environment / .env, not constructor arguments.
settings = Settings()  # type: ignore[call-arg]
