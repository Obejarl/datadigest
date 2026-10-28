"""Pick the profiling engine for a file on disk: pandas for small files, Spark for big ones."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datadigest.config import Settings, get_settings
from datadigest.core.loader import LoadError, load_csv
from datadigest.core.profile import build_profile
from datadigest.core.spark_profile import PARQUET_SUFFIX, build_profile_spark, spark_available

ENGINES = ("auto", "pandas", "spark")


def choose_engine(path: Path, requested: str = "auto", settings: Settings | None = None) -> str:
    """ "auto" means Spark for Parquet and for files over SPARK_MIN_MB when Spark is installed."""
    settings = settings or get_settings()
    if requested not in ENGINES:
        raise ValueError(f"engine must be one of {', '.join(ENGINES)}")
    if requested != "auto":
        return requested
    if path.suffix.lower() == PARQUET_SUFFIX:
        return "spark"
    if path.stat().st_size >= settings.spark_min_bytes and spark_available():
        return "spark"
    return "pandas"


def profile_path(path: Path, engine: str = "auto", settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    engine = choose_engine(path, engine, settings)
    if engine == "spark":
        return build_profile_spark(path, settings)
    if path.suffix.lower() == PARQUET_SUFFIX:
        raise LoadError("Parquet files need the Spark engine")
    return build_profile(load_csv(path.read_bytes(), max_rows=settings.max_rows))
