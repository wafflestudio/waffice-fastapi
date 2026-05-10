"""add graduation status

Revision ID: 796533bda978
Revises: f414a90934a1
Create Date: 2026-05-05 02:40:58.037087

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "796533bda978"
down_revision: Union[str, None] = "f414a90934a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add graduation_status enum column. Use enum names to match SQLAlchemy Enum
    graduation_enum = sa.Enum(
        "UNDERGRADUATE",
        "GRADUATED",
        "LEAVE_OF_ABSENCE",
        "GRADUATE_STUDENT",
        name="graduationstatus",
    )
    graduation_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "graduation_status",
            graduation_enum,
            nullable=False,
            server_default="UNDERGRADUATE",
        ),
    )

    # remove server default to match app behavior (optional)
    op.alter_column("users", "graduation_status", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "graduation_status")
    # In MySQL, ENUM types are per-column; no separate type drop required.
