"""add faculty_chart_visibility table for the admin-managed chart sharing map

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-06

One row holds which analytics charts the faculty role is allowed to see.
An administrator edits the map in the Analytics tab's "Manage faculty
access" panel; every faculty account reads the same map, so the setting is
the shared house rule rather than a per-user preference.

The table starts EMPTY on purpose. Resolution (app/services/faculty_charts.py)
falls back to the registry defaults when there is no row, and every chart
that exists at this point defaults to visible -- so deploying this migration
changes nothing for anyone until an administrator saves a change. Charts
added in later releases default to hidden in the registry, which needs no
further migration.

``payload`` is a JSON document (Text) keyed by chart key with boolean values,
so a chart is a new key rather than a new column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "faculty_chart_visibility",
        sa.Column("id", sa.String(36), primary_key=True),
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


def downgrade() -> None:
    op.drop_table("faculty_chart_visibility")
