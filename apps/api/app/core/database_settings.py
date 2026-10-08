from pydantic_settings import BaseSettings, SettingsConfigDict


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

    The defaults are the local Docker Compose development roles.
    """

    database_url: str = "postgresql+psycopg://heroos_app:heroos_app_local@localhost:5433/heroos"
    migration_database_url: str = "postgresql+psycopg://heroos:heroos_local@localhost:5433/heroos"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo raw configuration (secrets, DSNs).
        hide_input_in_errors=True,
    )
