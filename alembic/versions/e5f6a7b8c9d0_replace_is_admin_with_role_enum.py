"""replace is_admin with role enum

Revision ID: e5f6a7b8c9d0
Revises: d7e3f1a2b4c5
Create Date: 2026-06-25 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d7e3f1a2b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("member", "leader", "admin", "admin_and_leader", name="userrole"),
            nullable=False,
            server_default="member",
        ),
    )
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1")
    op.drop_index("idx_users_is_admin", table_name="users")
    op.drop_column("users", "is_admin")
    op.create_index("idx_users_role", "users", ["role"])


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE users SET is_admin = 1 WHERE role IN ('admin', 'admin_and_leader')"
    )
    op.drop_index("idx_users_role", table_name="users")
    op.drop_column("users", "role")
    op.create_index("idx_users_is_admin", "users", ["is_admin"])
