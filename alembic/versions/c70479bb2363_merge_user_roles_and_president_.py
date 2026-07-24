"""merge user-roles and president-signature heads

Revision ID: c70479bb2363
Revises: 29dd08592b64, d1e2f3a4b5c6
Create Date: 2026-07-24 11:07:31.799198

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c70479bb2363"
down_revision: Union[str, None] = ("29dd08592b64", "d1e2f3a4b5c6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
