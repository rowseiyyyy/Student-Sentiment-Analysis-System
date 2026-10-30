"""remove saved dashboard layout editing

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_dashboard_layouts_name", table_name="dashboard_layouts")
    op.drop_table("dashboard_layouts")


def downgrade() -> None:
    op.create_table(
        "dashboard_layouts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_dashboard_layouts_name", "dashboard_layouts", ["name"], unique=True
    )
