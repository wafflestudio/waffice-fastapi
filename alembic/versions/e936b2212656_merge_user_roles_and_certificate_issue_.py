"""merge user-roles and certificate-issue-number heads

Revision ID: e936b2212656
Revises: c70479bb2363, e2f3a4b5c6d7
Create Date: 2026-07-24 21:59:00.914017

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e936b2212656"
down_revision: Union[str, None] = ("c70479bb2363", "e2f3a4b5c6d7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
