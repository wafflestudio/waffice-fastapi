"""replace team_name with project_id in user_activities

Revision ID: c3f8a2e91d74
Revises: 59e1d704e6e2
Create Date: 2026-06-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c3f8a2e91d74"
down_revision: Union[str, None] = "59e1d704e6e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_activities",
        sa.Column("project_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_activities_project_id",
        "user_activities",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_activities_project_id", "user_activities", ["project_id"])
    op.drop_column("user_activities", "team_name")


def downgrade() -> None:
    op.add_column(
        "user_activities",
        sa.Column(
            "team_name", sa.String(length=200), nullable=False, server_default=""
        ),
    )
    op.drop_index("idx_activities_project_id", table_name="user_activities")
    op.drop_constraint(
        "fk_user_activities_project_id", "user_activities", type_="foreignkey"
    )
    op.drop_column("user_activities", "project_id")
