from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection configuration only.

    Kept separate from the API ``Settings`` so tools that only need the database
    (Alembic migrations) do not require environment or authentication
    configuration. ``DATABASE_URL`` remains the single connection setting.
    """

    database_url: str = "postgresql+psycopg://heroos:heroos_local@localhost:5433/heroos"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo raw configuration (secrets, DSNs).
        hide_input_in_errors=True,
    )
