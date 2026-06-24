"""expand approval requests

Revision ID: e2b1c4d5a6f7
Revises: c951e903b294
Create Date: 2026-06-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b1c4d5a6f7"
down_revision: Union[str, None] = "c951e903b294"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE approval_requests MODIFY action_type "
        "ENUM('USER_JOIN','HISTORY_CREATE','HISTORY_UPDATE','HISTORY_DELETE') "
        "NOT NULL"
    )
    op.drop_constraint(
        "approval_requests_ibfk_1", "approval_requests", type_="foreignkey"
    )
    op.drop_constraint("approvers_ibfk_2", "approvers", type_="foreignkey")

    op.add_column(
        "approval_requests", sa.Column("reviewer_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "approval_requests", sa.Column("review_comment", sa.Text(), nullable=True)
    )
    op.add_column(
        "approval_requests", sa.Column("reviewed_at", sa.BigInteger(), nullable=True)
    )
    op.alter_column(
        "approval_requests",
        "project_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "approval_requests",
        "body",
        existing_type=sa.Text(),
        type_=sa.JSON(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_approval_requests_project_id_projects",
        "approval_requests",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_approval_requests_reviewer_id_users",
        "approval_requests",
        "users",
        ["reviewer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_approval_requests_project_id",
        "approval_requests",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "idx_approval_requests_requester_id",
        "approval_requests",
        ["requester_id"],
        unique=False,
    )
    op.create_index(
        "idx_approval_requests_reviewer_id",
        "approval_requests",
        ["reviewer_id"],
        unique=False,
    )

    op.alter_column(
        "approvers",
        "project_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_approvers_project_id_projects",
        "approvers",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE approval_requests SET action_type = 'HISTORY_UPDATE' "
        "WHERE action_type = 'HISTORY_DELETE'"
    )
    op.drop_constraint(
        "fk_approvers_project_id_projects", "approvers", type_="foreignkey"
    )
    op.alter_column(
        "approvers",
        "project_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "approvers_ibfk_2",
        "approvers",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("idx_approval_requests_reviewer_id", table_name="approval_requests")
    op.drop_index("idx_approval_requests_requester_id", table_name="approval_requests")
    op.drop_index("idx_approval_requests_project_id", table_name="approval_requests")
    op.drop_constraint(
        "fk_approval_requests_reviewer_id_users",
        "approval_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_approval_requests_project_id_projects",
        "approval_requests",
        type_="foreignkey",
    )
    op.alter_column(
        "approval_requests",
        "body",
        existing_type=sa.JSON(),
        type_=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "approval_requests",
        "project_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "approval_requests_ibfk_1",
        "approval_requests",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("approval_requests", "reviewed_at")
    op.drop_column("approval_requests", "review_comment")
    op.drop_column("approval_requests", "reviewer_id")
    op.execute(
        "ALTER TABLE approval_requests MODIFY action_type "
        "ENUM('USER_JOIN','HISTORY_CREATE','HISTORY_UPDATE') NOT NULL"
    )
