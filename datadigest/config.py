from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment variables (DATABASE_URL, REDIS_URL, ...) or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./datadigest.db"
    # Without Redis the API processes uploads itself (inline mode); with it, workers do.
    redis_url: str | None = None
    queue_name: str = "datadigest:jobs"
    max_upload_mb: int = 10
    max_rows: int = 200_000
    retention_days: int = 7
    # A job still queued/processing after this long is treated as lost (crashed worker, flushed Redis).
    stuck_after_minutes: int = 15
    # Bundled demo files offered on the dashboard ("Try a sample").
    samples_dir: str = "samples"
    # Upper bound for one solver run; HiGHS returns its best plan so far when it is reached.
    opt_time_limit_seconds: float = 10.0

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
