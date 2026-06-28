"""update audit_log action enum for role change

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: add ROLE_CHANGED while keeping old values
    op.execute(
        """
        ALTER TABLE audit_logs MODIFY COLUMN action ENUM(
            'QUALIFICATION_CHANGED',
            'ADMIN_GRANTED',
            'ADMIN_REVOKED',
            'ROLE_CHANGED',
            'PROJECT_JOINED',
            'PROJECT_LEFT',
            'PROJECT_ROLE_CHANGED'
        ) NOT NULL
        """
    )
    # Step 2: migrate existing rows
    op.execute(
        """
        UPDATE audit_logs
        SET action = 'ROLE_CHANGED'
        WHERE action IN ('ADMIN_GRANTED', 'ADMIN_REVOKED')
        """
    )
    # Step 3: remove old values
    op.execute(
        """
        ALTER TABLE audit_logs MODIFY COLUMN action ENUM(
            'QUALIFICATION_CHANGED',
            'ROLE_CHANGED',
            'PROJECT_JOINED',
            'PROJECT_LEFT',
            'PROJECT_ROLE_CHANGED'
        ) NOT NULL
        """
    )


def downgrade() -> None:
    # ROLE_CHANGED 행이 있으면 되돌릴 수 없으므로 QUALIFICATION_CHANGED로 변환
    op.execute(
        "UPDATE audit_logs SET action = 'QUALIFICATION_CHANGED' WHERE action = 'ROLE_CHANGED'"
    )
    op.execute(
        """
        ALTER TABLE audit_logs MODIFY COLUMN action ENUM(
            'QUALIFICATION_CHANGED',
            'ADMIN_GRANTED',
            'ADMIN_REVOKED',
            'PROJECT_JOINED',
            'PROJECT_LEFT',
            'PROJECT_ROLE_CHANGED'
        ) NOT NULL
        """
    )
