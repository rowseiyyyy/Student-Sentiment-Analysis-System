"""merge strengths and areas_for_improvement into share_your_thoughts

Revision ID: 4e9ba8618cde
Revises: 0007
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "4e9ba8618cde"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluations",
        sa.Column("share_your_thoughts", sa.Text(), nullable=True),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE evaluations
            SET share_your_thoughts = TRIM(
                CASE WHEN strengths IS NOT NULL AND strengths <> ''
                     THEN 'Strengths: ' || strengths ELSE '' END
                ||
                CASE WHEN areas_for_improvement IS NOT NULL AND areas_for_improvement <> ''
                     THEN (CASE WHEN strengths IS NOT NULL AND strengths <> '' THEN char(10) || char(10) ELSE '' END)
                          || 'Areas for improvement: ' || areas_for_improvement
                     ELSE '' END
            )
            WHERE (strengths IS NOT NULL AND strengths <> '')
               OR (areas_for_improvement IS NOT NULL AND areas_for_improvement <> '')
            """
        )
    )

    op.drop_column("evaluations", "strengths")
    op.drop_column("evaluations", "areas_for_improvement")


def downgrade() -> None:
    op.add_column("evaluations", sa.Column("strengths", sa.Text(), nullable=True))
    op.add_column("evaluations", sa.Column("areas_for_improvement", sa.Text(), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE evaluations
            SET strengths = share_your_thoughts
            WHERE share_your_thoughts IS NOT NULL AND share_your_thoughts <> ''
            """
        )
    )

    op.drop_column("evaluations", "share_your_thoughts")