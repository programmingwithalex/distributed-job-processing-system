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
    kafka_bootstrap_servers: str = "localhost:29092"
    job_events_topic: str = "job-events.v1"
    job_events_partition_count: int = 3
    job_history_consumer_group: str = "job-history-v1"
    job_event_publisher_poll_interval_seconds: float = 1.0
    job_event_publisher_batch_size: int = 100
    job_event_delivery_timeout_seconds: float = 10.0
    default_maximum_attempt_count: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_application_settings() -> ApplicationSettings:
    """
    Return the cached application settings instance.

    Returns:
        Cached application settings
    """
    return ApplicationSettings()
