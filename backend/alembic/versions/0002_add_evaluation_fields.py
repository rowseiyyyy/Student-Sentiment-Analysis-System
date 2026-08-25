"""add, strengths, areas_for_improvement, ratings to evaluations;
add student_id, course, year_level to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to users table
    op.add_column("users", sa.Column("student_id", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("course", sa.String(150), nullable=True))
    op.add_column("users", sa.Column("year_level", sa.String(50), nullable=True))
    op.create_index("ix_users_student_id", "users", ["student_id"], unique=False)

    # Add columns to evaluations table
    op.add_column("evaluations", sa.Column("strengths", sa.Text, nullable=True))
    op.add_column("evaluations", sa.Column("areas_for_improvement", sa.Text, nullable=True))
    op.add_column("evaluations", sa.Column("ratings", sa.JSON, nullable=True))


def downgrade() -> None:
    # Remove columns from evaluations table
    op.drop_column("evaluations", "ratings")
    op.drop_column("evaluations", "areas_for_improvement")
    op.drop_column("evaluations", "strengths")

    # Remove columns from users table
    op.drop_index("ix_users_student_id", table_name="users")
    op.drop_column("users", "year_level")
    op.drop_column("users", "course")
    op.drop_column("users", "student_id")
