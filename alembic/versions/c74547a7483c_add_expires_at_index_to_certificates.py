"""add expires_at index to certificates

Revision ID: c74547a7483c
Revises: e936b2212656
Create Date: 2026-07-24 22:58:55.802326

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c74547a7483c"
down_revision: Union[str, None] = "e936b2212656"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_certificates_expires_at", "certificates", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_certificates_expires_at", table_name="certificates")
