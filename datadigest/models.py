import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String
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


class Role(enum.StrEnum):
    ADMIN = "admin"  # sees every dataset and manages users
    MEMBER = "member"  # sees their own datasets


class User(Base):
    """An account (AUTH_MODE=accounts). Deleting a user deletes their datasets."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # SHA-256 of the user's API token; the token itself is shown once and never stored.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Who uploaded it. Empty when accounts are off, and for datasets from before they were switched on.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=Status.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    rows: Mapped[int | None] = mapped_column(Integer, default=None)
    cols: Mapped[int | None] = mapped_column(Integer, default=None)
    warnings_count: Mapped[int | None] = mapped_column(Integer, default=None)
    quality_score: Mapped[int | None] = mapped_column(Integer, default=None)
    # Set for files read from LARGE_DATA_DIR instead of uploaded (there is no DatasetFile row then).
    source_path: Mapped[str | None] = mapped_column(String(255), default=None)
    # Which profiler produced the result: "pandas" or "spark".
    engine: Mapped[str | None] = mapped_column(String(16), default=None)
    # JSONB on PostgreSQL (indexable, compact), plain JSON on SQLite.
    profile: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=None, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    # Set on upload and again on every re-run: the start of the current attempt.
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    # queued_at -> started_at is time waiting in the queue, started_at -> finished_at is service time.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    file: Mapped["DatasetFile"] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class DatasetFile(Base):
    """Raw upload, kept in its own table so listing datasets never loads file contents."""

    __tablename__ = "dataset_files"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary)


class Optimization(Base):
    """One solver run (production plan, transport plan, ...) on a dataset's raw file.

    It has no owner of its own: it belongs to its dataset, and is deleted with it.
    """

    __tablename__ = "optimizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    params: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    status: Mapped[str] = mapped_column(String(16), default=Status.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    # Copied out of the result so lists do not need to load it.
    result_status: Mapped[str | None] = mapped_column(String(16), default=None)
    objective: Mapped[float | None] = mapped_column(Float, default=None)
    uplift_pct: Mapped[float | None] = mapped_column(Float, default=None)
    result: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=None, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
