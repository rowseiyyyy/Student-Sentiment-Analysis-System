"""add course and year_level to evaluations

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-11

Student submissions are anonymous (no auth header, no student_id), so the
admin Responses view read course/year_level from the (never created) User
record and always rendered "N/A". The form's demographic selections now live
on the evaluation row itself.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("course", sa.String(150), nullable=True))
    op.add_column("evaluations", sa.Column("year_level", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("evaluations", "year_level")
    op.drop_column("evaluations", "course")
