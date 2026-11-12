"""make sure the optimizations table exists

An unreleased build of 0.8.0 dropped this table (its revision 0006, since removed). Databases
that were upgraded with that build get the table back, empty; every other database already has
it and is left untouched.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("optimizations"):
        return
    op.create_table(
        "optimizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("params", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("result_status", sa.String(16), nullable=True),
        sa.Column("objective", sa.Float(), nullable=True),
        sa.Column("uplift_pct", sa.Float(), nullable=True),
        sa.Column("result", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_optimizations_dataset_id", "optimizations", ["dataset_id"])
    op.create_index("ix_optimizations_status", "optimizations", ["status"])
    op.create_index("ix_optimizations_created_at", "optimizations", ["created_at"])


def downgrade() -> None:
    # Nothing to undo: the table belongs to revision 0004, which drops it on its own downgrade.
    pass
