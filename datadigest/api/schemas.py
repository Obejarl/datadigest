import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    created_at: datetime
    finished_at: datetime | None
