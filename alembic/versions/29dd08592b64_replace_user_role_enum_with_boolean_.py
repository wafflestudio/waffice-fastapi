"""replace user role enum with boolean flags

Revision ID: 29dd08592b64
Revises: f2a7b7ac51e6
Create Date: 2026-07-15 21:05:10.541763

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29dd08592b64"
down_revision: Union[str, None] = "f2a7b7ac51e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_leader", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("is_president", sa.Boolean(), nullable=False, server_default="0"),
    )

    op.execute(
        "UPDATE users SET is_leader = 1 "
        "WHERE role IN ('LEADER', 'ADMIN_AND_LEADER', 'LEADER_AND_PRESIDENT')"
    )
    op.execute(
        "UPDATE users SET is_admin = 1 "
        "WHERE role IN ('ADMIN', 'PRESIDENT', 'ADMIN_AND_LEADER', 'LEADER_AND_PRESIDENT')"
    )
    op.execute(
        "UPDATE users SET is_president = 1 "
        "WHERE role IN ('PRESIDENT', 'LEADER_AND_PRESIDENT')"
    )

    op.drop_index("idx_users_role", table_name="users")
    op.drop_column("users", "role")

    op.create_index("idx_users_is_leader", "users", ["is_leader"])
    op.create_index("idx_users_is_admin", "users", ["is_admin"])
    op.create_index("idx_users_is_president", "users", ["is_president"])


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            mysql.ENUM(
                "MEMBER",
                "LEADER",
                "ADMIN",
                "PRESIDENT",
                "ADMIN_AND_LEADER",
                "LEADER_AND_PRESIDENT",
                name="userrole",
            ),
            nullable=False,
            server_default="MEMBER",
        ),
    )
    op.execute(
        """
        UPDATE users SET role = CASE
            WHEN is_leader = 1 AND is_president = 1 THEN 'LEADER_AND_PRESIDENT'
            WHEN is_leader = 1 AND is_admin = 1 THEN 'ADMIN_AND_LEADER'
            WHEN is_president = 1 THEN 'PRESIDENT'
            WHEN is_admin = 1 THEN 'ADMIN'
            WHEN is_leader = 1 THEN 'LEADER'
            ELSE 'MEMBER'
        END
        """
    )

    op.drop_index("idx_users_is_leader", table_name="users")
    op.drop_index("idx_users_is_admin", table_name="users")
    op.drop_index("idx_users_is_president", table_name="users")
    op.drop_column("users", "is_leader")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "is_president")

    op.create_index("idx_users_role", "users", ["role"])
