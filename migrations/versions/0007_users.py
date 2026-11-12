"""user accounts, and an owner on every dataset

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("token_hash", name="uq_users_token_hash"),
    )
    # Existing datasets keep an empty owner: administrators see them, members do not.
    with op.batch_alter_table("datasets") as batch:
        batch.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_datasets_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_datasets_owner_id", ["owner_id"])


def downgrade() -> None:
    with op.batch_alter_table("datasets") as batch:
        batch.drop_index("ix_datasets_owner_id")
        batch.drop_constraint("fk_datasets_owner_id_users", type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_table("users")
