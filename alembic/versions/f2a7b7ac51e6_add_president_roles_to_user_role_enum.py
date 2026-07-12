"""add president roles to user_role enum

Revision ID: f2a7b7ac51e6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12 08:05:54.190502

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7b7ac51e6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=mysql.ENUM("MEMBER", "LEADER", "ADMIN", "ADMIN_AND_LEADER"),
        type_=mysql.ENUM(
            "MEMBER",
            "LEADER",
            "ADMIN",
            "PRESIDENT",
            "ADMIN_AND_LEADER",
            "LEADER_AND_PRESIDENT",
        ),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=mysql.ENUM(
            "MEMBER",
            "LEADER",
            "ADMIN",
            "PRESIDENT",
            "ADMIN_AND_LEADER",
            "LEADER_AND_PRESIDENT",
        ),
        type_=mysql.ENUM("MEMBER", "LEADER", "ADMIN", "ADMIN_AND_LEADER"),
        nullable=False,
    )
