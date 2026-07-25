"""merge render-draft and issue-number heads

Revision ID: 3b02e9b6b13d
Revises: 1b5de17a17d6, c74547a7483c
Create Date: 2026-07-24 23:22:06.679199

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b02e9b6b13d"
down_revision: Union[str, None] = ("1b5de17a17d6", "c74547a7483c")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
