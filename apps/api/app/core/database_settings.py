from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfigurationError(RuntimeError):
    """A required database URL is not configured. Messages never contain values."""


class DatabaseSettings(BaseSettings):
    """Database connection configuration only.

    Kept separate from the API ``Settings`` so tools that only need the database
    (Alembic migrations) do not require environment or authentication
    configuration.

    Two connections with different privileges (docs/architecture/tenant-isolation.md):

    - ``DATABASE_URL``: the API runtime role. Not superuser, no BYPASSRLS, owns
      no tables; subject to Row-Level Security.
    - ``MIGRATION_DATABASE_URL``: the migration/admin role that owns the schema.
      Used by Alembic only, never by the API.

    There are no defaults, in any environment: a committed default would be a
    committed credential (docs/operations/database-credentials.md). Local
    development generates both into the untracked root ``.env`` with
    ``make env-init``. An empty value counts as unset.

    Both URLs carry a password, so they are ``SecretStr``: they never appear in
    ``repr``, logs, ``model_dump`` output or validation errors. Call
    ``require_*()`` only where a driver needs the URL.
    """

    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo raw configuration (secrets, DSNs).
        hide_input_in_errors=True,
    )

    @field_validator("database_url", "migration_database_url", mode="after")
    @classmethod
    def _empty_is_unset(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            return None
        return value

    def require_database_url(self) -> str:
        return _require(self.database_url, "DATABASE_URL")

    def require_migration_database_url(self) -> str:
        return _require(self.migration_database_url, "MIGRATION_DATABASE_URL")


def _require(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise DatabaseConfigurationError(
            f"{name} is not set; for local development run `make env-init` "
            "(docs/operations/database-credentials.md)"
        )
    return value.get_secret_value()
