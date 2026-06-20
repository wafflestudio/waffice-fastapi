"""rename user_histories to audit_logs

Revision ID: 59e1d704e6e2
Revises: 48d09036fcb7
Create Date: 2026-06-20 15:49:34.565561

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "59e1d704e6e2"
down_revision: Union[str, None] = "48d09036fcb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "audit_logs" not in existing_tables:
        op.rename_table("user_histories", "audit_logs")
        # Create new indexes before dropping old ones (FK constraint requires index)
        op.create_index("idx_audit_logs_user_id", "audit_logs", ["user_id"])
        op.create_index("idx_audit_logs_action", "audit_logs", ["action"])
        op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"])
        op.drop_index("idx_histories_user_id", table_name="audit_logs")
        op.drop_index("idx_histories_action", table_name="audit_logs")
        op.drop_index("idx_histories_created_at", table_name="audit_logs")
    elif "user_histories" in existing_tables:
        # audit_logs already exists separately — drop the leftover user_histories
        op.drop_table("user_histories")


def downgrade() -> None:
    op.rename_table("audit_logs", "user_histories")
