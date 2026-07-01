"""add temporary member support

Make users.email nullable (temporary members have no OAuth email) and add an
is_temporary flag plus supporting indexes for roster import.

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-06-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "is_temporary",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index("idx_users_is_temporary", "users", ["is_temporary"])
    op.create_index("idx_users_student_id", "users", ["student_id"])


def downgrade() -> None:
    op.drop_index("idx_users_student_id", table_name="users")
    op.drop_index("idx_users_is_temporary", table_name="users")
    op.drop_column("users", "is_temporary")
    # Reverting email to NOT NULL requires no rows with NULL email.
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=255),
        nullable=False,
    )
