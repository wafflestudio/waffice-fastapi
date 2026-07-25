"""add requested qualification to users

Revision ID: 9d21f3a84b67
Revises: 8af105d95228
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9d21f3a84b67"
down_revision: Union[str, None] = "8af105d95228"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "requested_qualification",
            sa.Enum(
                "PENDING",
                "ASSOCIATE",
                "REGULAR",
                "ACTIVE",
                name="qualification",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "privacy_policy_agreed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "terms_agreed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "marketing_agreed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "marketing_agreed")
    op.drop_column("users", "terms_agreed")
    op.drop_column("users", "privacy_policy_agreed")
    op.drop_column("users", "requested_qualification")
