import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from datadigest.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Status(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=Status.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    rows: Mapped[int | None] = mapped_column(Integer, default=None)
    cols: Mapped[int | None] = mapped_column(Integer, default=None)
    warnings_count: Mapped[int | None] = mapped_column(Integer, default=None)
    # JSONB on PostgreSQL (indexable, compact), plain JSON on SQLite.
    profile: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=None, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    file: Mapped["DatasetFile"] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DatasetFile(Base):
    """Raw upload, kept in its own table so listing datasets never loads file contents."""

    __tablename__ = "dataset_files"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)
