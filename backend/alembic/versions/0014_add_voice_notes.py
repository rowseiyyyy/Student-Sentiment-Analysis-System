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
    # Idempotency guard: if the table already exists (e.g. a prior deploy
    # created it but crashed before recording the Alembic version), skip
    # the CREATE TABLE and let the deploy proceed instead of failing with
    # MySQL error 1050 "Table 'voice_notes' already exists".
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("voice_notes"):
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
    else:
        # Table already present — verify it actually matches the schema this
        # migration defines before treating it as up to date. A stale/partial
        # table from a failed attempt should surface loudly, not be stamped
        # over silently.
        expected = {
            "id", "message", "sentiment", "confidence_score",
            "algorithm_used", "processing_time_ms", "created_at",
        }
        actual = {c["name"] for c in insp.get_columns("voice_notes")}
        missing = expected - actual
        if missing:
            raise RuntimeError(
                "voice_notes table already exists but is missing expected "
                f"columns: {sorted(missing)}. It is likely a stale/partial "
                "table from an earlier failed deploy — DROP it manually and "
                "re-run this migration instead of stamping over broken schema."
            )


def downgrade() -> None:
    op.drop_index("ix_voice_notes_created_at", table_name="voice_notes")
    op.drop_index("ix_voice_notes_sentiment", table_name="voice_notes")
    op.drop_table("voice_notes")
