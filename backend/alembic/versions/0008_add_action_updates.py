"""add action_updates table for the public Action Taken bulletin

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-29

Aggregate, public-facing bulletin posts written by admins so students
can see that feedback leads to action. No student-identifiable data is
stored on this table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category", sa.Enum("Faculty", "Staff", "Payment", "Facilities", name="evaluationcategory"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("acknowledged", "in_progress", "resolved", name="actionstatus"),
            nullable=False,
            server_default="acknowledged",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("internal_reference", sa.String(200), nullable=True),
        sa.Column("date_posted", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("date_updated", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_action_updates_date_posted", ["date_posted"])
    op.create_index("ix_action_updates_category", ["category"])


def downgrade() -> None:
    op.drop_index("ix_action_updates_category", table_name="action_updates")
    op.drop_index("ix_action_updates_date_posted", table_name="action_updates")
    op.drop_table("action_updates")
    sa.Enum(name="actionstatus").drop(op.get_bind(), checkfirst=True)
