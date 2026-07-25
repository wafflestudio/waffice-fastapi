"""merge user-roles and certificate-render-draft heads

Revision ID: 1b5de17a17d6
Revises: c70479bb2363, e2f3a4b5c6d7
Create Date: 2026-07-24 14:04:51.952487

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b5de17a17d6"
down_revision: Union[str, None] = ("c70479bb2363", "e2f3a4b5c6d7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
