from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_pairs(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").replace("\n", ",").split(",") if item.strip()]


class Settings(BaseSettings):
    """Read from environment variables (DATABASE_URL, REDIS_URL, ...) or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./datadigest.db"
    # Without Redis the API processes uploads itself (inline mode); with it, workers do.
    redis_url: str | None = None
    queue_name: str = "datadigest:jobs"
    max_upload_mb: int = 10
    max_rows: int = 200_000
    # The Statistics tab's tests run on at most this many rows; larger files are sampled at random.
    # More rows cost time and memory in the worker and rarely change an effect size.
    stats_max_rows: int = Field(50_000, ge=1_000, le=5_000_000)
    retention_days: int = 7
    # A job still queued/processing after this long is treated as lost (crashed worker, flushed Redis).
    stuck_after_minutes: int = 15
    # Bundled demo files offered on the dashboard ("Try a sample").
    samples_dir: str = "samples"
    # Upper bound for one solver run; HiGHS returns its best plan so far when it is reached.
    opt_time_limit_seconds: float = 10.0
    # Reliable queue: a job a worker took but did not finish within this time is given back
    # to the queue, up to max_job_attempts times, then parked in the dead-letter list.
    job_visibility_seconds: float = 120.0
    max_job_attempts: int = 3
    # Each worker serves Prometheus metrics on this port (0 disables it).
    worker_metrics_port: int = 9100
    # Big files are profiled by Spark (optional: pip install -r requirements-spark.txt, plus Java).
    # Files read from this directory instead of being uploaded; empty disables the feature.
    large_data_dir: str | None = None
    # With engine "auto", files at least this large go to Spark (when it is installed).
    spark_min_mb: int = 100
    # local[*] runs Spark inside the worker process. A cluster address (spark://host:7077, or
    # k8s://...) sends the work to executors; they must see the file at the same path, so
    # LARGE_DATA_DIR has to be shared storage mounted identically on the worker and the executors.
    spark_master: str = "local[*]"
    # The address executors use to call back to the worker (the Spark driver). In Kubernetes: the pod IP.
    spark_driver_host: str | None = None
    spark_executor_memory: str | None = None
    # Any other Spark settings, as key=value pairs separated by commas or line breaks, e.g.
    # spark.executor.cores=2,spark.cores.max=4
    spark_conf: str | None = None
    # Where Spark is installed; only needed when the default (inside pyspark) cannot be used, e.g. on
    # Windows when the install path has non-ASCII characters.
    spark_home: str | None = None
    spark_driver_memory: str | None = "2g"
    spark_shuffle_partitions: int = 8
    # When set, every page and API call needs it (see datadigest/api/auth.py). Empty means off.
    access_token: str | None = None
    # "accounts": people sign in with an email and a password and see only their own datasets
    # (see datadigest/accounts.py). Takes precedence over ACCESS_TOKEN. Empty means off.
    auth_mode: str | None = None
    # Signs the session cookies in accounts mode. Set it, and set the same value on every API
    # replica; without it a random one is used and sessions end when the process restarts.
    secret_key: str | None = None
    # The first administrator, created at startup when there are no users yet.
    admin_email: str | None = None
    admin_password: str | None = None

    @field_validator(
        "access_token",
        "large_data_dir",
        "spark_home",
        "spark_driver_host",
        "spark_executor_memory",
        "spark_conf",
        "auth_mode",
        "secret_key",
        "admin_email",
        "admin_password",
        mode="before",
    )
    @classmethod
    def _blank_means_off(cls, value):
        return (value or "").strip() or None

    @field_validator("auth_mode")
    @classmethod
    def _known_mode(cls, value):
        if value not in (None, "accounts"):
            raise ValueError("AUTH_MODE must be empty or 'accounts'")
        return value

    @field_validator("spark_conf")
    @classmethod
    def _spark_pairs(cls, value):
        for item in _split_pairs(value):
            key, sep, _ = item.partition("=")
            if not sep or not key.strip().startswith("spark."):
                raise ValueError(f"SPARK_CONF entries look like spark.some.key=value, not '{item}'")
        return value

    @property
    def spark_conf_pairs(self) -> list[tuple[str, str]]:
        pairs = (item.partition("=") for item in _split_pairs(self.spark_conf))
        return [(key.strip(), value.strip()) for key, _, value in pairs]

    @property
    def spark_is_local(self) -> bool:
        return self.spark_master.startswith("local") and not self.spark_master.startswith("local-cluster")

    @property
    def accounts_enabled(self) -> bool:
        return self.auth_mode == "accounts"

    @property
    def spark_min_bytes(self) -> int:
        return self.spark_min_mb * 1024 * 1024

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
