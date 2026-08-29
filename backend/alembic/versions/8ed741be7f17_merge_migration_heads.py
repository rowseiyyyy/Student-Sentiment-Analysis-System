"""merge migration heads

Revision ID: 8ed741be7f17
Revises: 0009, 4e9ba8618cde
Create Date: 2026-08-30 07:31:15.804458

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ed741be7f17'
down_revision: Union[str, None] = ('0009', '4e9ba8618cde')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
