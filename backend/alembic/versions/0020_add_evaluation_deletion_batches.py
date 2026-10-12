"""add reversible evaluation deletion batches

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_deletion_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.Column("snapshots", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_evaluation_deletion_batches_created_by",
        "evaluation_deletion_batches",
        ["created_by"],
    )
    op.create_index(
        "ix_evaluation_deletion_batches_expires_at",
        "evaluation_deletion_batches",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_deletion_batches_expires_at",
        table_name="evaluation_deletion_batches",
    )
    op.drop_index(
        "ix_evaluation_deletion_batches_created_by",
        table_name="evaluation_deletion_batches",
    )
    op.drop_table("evaluation_deletion_batches")
