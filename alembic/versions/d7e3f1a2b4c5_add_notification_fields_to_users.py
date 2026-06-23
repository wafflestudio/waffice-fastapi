"""add notification fields to users

Revision ID: d7e3f1a2b4c5
Revises: c3f8a2e91d74
Create Date: 2026-06-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d7e3f1a2b4c5"
down_revision: Union[str, None] = "c3f8a2e91d74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "notification_channel",
            sa.Enum("EMAIL", "SMS", "BOTH", name="notificationchannel"),
            nullable=False,
            server_default="EMAIL",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_channel")
    op.drop_column("users", "contact_email")
