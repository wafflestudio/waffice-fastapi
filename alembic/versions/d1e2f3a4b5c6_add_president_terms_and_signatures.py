"""add president terms and signatures

Adds the 회장(president) domain: president_terms (tracks who is the 현직
회장 with an at-most-one-open-term invariant enforced at the DB level via a
MySQL 8 generated column + unique index) and certificate_signatures (one
signature image per president, used by the activity-certificate feature).

Revision ID: d1e2f3a4b5c6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "president_terms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("ended_at", sa.Date(), nullable=True),
        # 현직 회장 불변식(열린 임기는 최대 1개)을 DB 레벨에서 강제하는 생성
        # 컬럼. ended_at이 NULL이면 1, 아니면 NULL 이 되고, MySQL UNIQUE
        # 인덱스는 NULL끼리 충돌하지 않으므로 종료된 임기는 여러 개 허용되지만
        # 열린 임기는 uq_president_current 유니크 인덱스에 의해 하나만
        # 허용된다.
        sa.Column(
            "is_current",
            mysql.TINYINT(),
            sa.Computed("IF(ended_at IS NULL, 1, NULL)", persisted=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("is_current", name="uq_president_current"),
    )
    op.create_index(
        "idx_president_terms_user_id", "president_terms", ["user_id"], unique=False
    )

    op.create_table(
        "certificate_signatures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_certificate_signatures_user_id"),
    )


def downgrade() -> None:
    op.drop_table("certificate_signatures")

    # NOTE: idx_president_terms_user_id is the *only* index covering
    # president_terms' FK column, so MySQL rejects an explicit DROP INDEX on
    # it while the FK constraint is still attached (error 1553). drop_table
    # removes a table's FKs and indexes together, so it is intentionally
    # left for drop_table to clean up rather than dropped explicitly first.
    op.drop_table("president_terms")
