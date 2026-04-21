from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_env: str = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/jobs"
    celery_broker_url: str = "amqp://guest:guest@localhost:5672//"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_application_settings() -> ApplicationSettings:
    """Return the cached application settings instance."""
    return ApplicationSettings()
