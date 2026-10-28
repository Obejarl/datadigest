import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    filename: str
    size_bytes: int
    status: str
    error: str | None
    rows: int | None
    cols: int | None
    warnings_count: int | None
    quality_score: int | None
    engine: str | None = None
    source_path: str | None = None
    created_at: datetime
    queued_at: datetime | None
    finished_at: datetime | None

    @field_validator("created_at", "queued_at", "finished_at")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite drops the timezone; we only ever store UTC, so put it back.
        # Without it the browser would read the time as local time.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class StatsOut(BaseModel):
    datasets: int
    by_status: dict[str, int]
    rows_profiled: int
    warnings_found: int
    avg_quality: float | None
    avg_seconds: float | None
    mode: str
    queue_depth: int | None
    queue_in_flight: int | None = None
    queue_dead: int | None = None


class OptimizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    kind: str
    name: str
    status: str
    error: str | None
    result_status: str | None
    objective: float | None
    uplift_pct: float | None
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None

    @field_validator("created_at", "queued_at", "started_at", "finished_at")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
