"""add is_mismatch, mismatch_type to evaluations

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-24

Adds the Likert-vs-sentiment disagreement flag described in
app/services/mismatch.py. is_mismatch/mismatch_type are a comparison
layer on top of the existing likert_sentiment/likert_average (0006)
and sentiment (0004) columns -- they do not replace or blend either.

Uses batch_alter_table because SQLite does not support
ALTER TABLE ... ALTER COLUMN ... SET NOT NULL directly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first so we can backfill existing rows before enforcing
    # NOT NULL, matching app/models/evaluation.py.
    with op.batch_alter_table("evaluations") as batch_op:
        batch_op.add_column(sa.Column("is_mismatch", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("mismatch_type", sa.String(30), nullable=True))

    # Existing rows predate the mismatch feature, so default them to "no mismatch".
    op.execute("UPDATE evaluations SET is_mismatch = 0 WHERE is_mismatch IS NULL")
    op.execute("UPDATE evaluations SET mismatch_type = 'none' WHERE mismatch_type IS NULL")

    # Now enforce NOT NULL + defaults, matching app/models/evaluation.py.
    # batch_alter_table rebuilds the table under the hood, which is how
    # SQLite supports constraint changes.
    with op.batch_alter_table("evaluations") as batch_op:
        batch_op.alter_column(
            "is_mismatch",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
        batch_op.alter_column(
            "mismatch_type",
            existing_type=sa.String(30),
            nullable=False,
            server_default="none",
        )
        batch_op.create_index("ix_evaluations_is_mismatch", ["is_mismatch"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("evaluations") as batch_op:
        batch_op.drop_index("ix_evaluations_is_mismatch")
        batch_op.drop_column("mismatch_type")
        batch_op.drop_column("is_mismatch")
