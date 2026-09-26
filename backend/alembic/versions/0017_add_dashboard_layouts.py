"""add dashboard_layouts table for the shared admin-editable widget layout

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-26

One row per layout name holds the per-widget width/height chosen by an
administrator. Every other role reads the same row, so the saved geometry is
the shared house style rather than a per-user preference.

``payload`` is a JSON document (Text) keyed "<tab>:<widget-id>" with
{"w": <grid units>, "h": <px>} values. JSON keeps this table stable as
widgets are added -- a new widget is a new key, not a new migration.

The unique constraint on ``name`` is what makes "one current layout per name"
true: a second concurrent save updates the existing row instead of creating a
duplicate the readers would have to arbitrate between.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_dashboard_layouts_name", table_name="dashboard_layouts")
    op.drop_table("dashboard_layouts")
