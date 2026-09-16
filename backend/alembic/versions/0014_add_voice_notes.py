"""add voice_notes table for the anonymous "Voice in a Box" stream

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-17

A separate open-ended feedback stream from the evaluations table:
free text + ML sentiment + timestamp only. NO student identifier,
course, instructor, or Likert fields — and it must never be merged
into the evaluation aggregates/KPIs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.String(20), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("algorithm_used", sa.String(120), nullable=True),
        sa.Column("processing_time_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_voice_notes_sentiment", "voice_notes", ["sentiment"])
    op.create_index("ix_voice_notes_created_at", "voice_notes", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_voice_notes_created_at", table_name="voice_notes")
    op.drop_index("ix_voice_notes_sentiment", table_name="voice_notes")
    op.drop_table("voice_notes")
