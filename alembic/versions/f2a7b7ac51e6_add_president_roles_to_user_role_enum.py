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
        existing_type=mysql.ENUM("member", "leader", "admin", "admin_and_leader"),
        type_=mysql.ENUM(
            "member",
            "leader",
            "admin",
            "president",
            "admin_and_leader",
            "leader_and_president",
        ),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=mysql.ENUM(
            "member",
            "leader",
            "admin",
            "president",
            "admin_and_leader",
            "leader_and_president",
        ),
        type_=mysql.ENUM("member", "leader", "admin", "admin_and_leader"),
        nullable=False,
    )
