"""add approval requests

Revision ID: c951e903b294
Revises: d7e3f1a2b4c5
Create Date: 2026-06-24 12:28:35.860894

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c951e903b294"
down_revision: Union[str, None] = "d7e3f1a2b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "APPROVED", "REJECTED", name="approvalstatus"),
            nullable=False,
        ),
        sa.Column(
            "action_type",
            sa.Enum(
                "USER_JOIN",
                "HISTORY_CREATE",
                "HISTORY_UPDATE",
                name="approvalactiontype",
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_approval_requests_action_type",
        "approval_requests",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "idx_approval_requests_created_at",
        "approval_requests",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_approval_requests_status", "approval_requests", ["status"], unique=False
    )

    op.create_table(
        "approvers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("approval_request_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approval_request_id"], ["approval_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_approvers_approval_request_id",
        "approvers",
        ["approval_request_id"],
        unique=False,
    )
    op.create_index(
        "idx_approvers_project_id", "approvers", ["project_id"], unique=False
    )
    op.create_index(
        "idx_approvers_request_user",
        "approvers",
        ["approval_request_id", "user_id"],
        unique=True,
    )
    op.create_index("idx_approvers_user_id", "approvers", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_approvers_user_id", table_name="approvers")
    op.drop_index("idx_approvers_request_user", table_name="approvers")
    op.drop_index("idx_approvers_project_id", table_name="approvers")
    op.drop_index("idx_approvers_approval_request_id", table_name="approvers")
    op.drop_table("approvers")

    op.drop_index("idx_approval_requests_status", table_name="approval_requests")
    op.drop_index("idx_approval_requests_created_at", table_name="approval_requests")
    op.drop_index("idx_approval_requests_action_type", table_name="approval_requests")
    op.drop_table("approval_requests")
