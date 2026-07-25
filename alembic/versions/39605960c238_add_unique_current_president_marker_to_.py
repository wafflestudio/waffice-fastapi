"""add unique current-president marker to users

Revision ID: 39605960c238
Revises: 3b02e9b6b13d
Create Date: 2026-07-25 01:05:26.068322

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "39605960c238"
down_revision: Union[str, None] = "3b02e9b6b13d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_president_marker",
            mysql.TINYINT(),
            sa.Computed("IF(is_president, 1, NULL)", persisted=False),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_users_current_president", "users", ["is_president_marker"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_current_president", "users", type_="unique")
    op.drop_column("users", "is_president_marker")
