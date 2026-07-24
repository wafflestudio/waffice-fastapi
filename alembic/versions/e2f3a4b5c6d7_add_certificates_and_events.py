"""add certificates and events

Adds the certificates (the issuance/draft records) and certificate_events
(append-only processing history) tables. This builds on top of the
president_terms/certificate_signatures tables added by
d1e2f3a4b5c6_add_president_terms_and_signatures.py.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("SELF", "DRAFT", name="certificatekind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("ISSUED", "ORIGINAL_PENDING", name="certificatestatus"),
            nullable=False,
        ),
        # 운영진용 발급 이력(list_history) 정렬 우선순위 생성 컬럼(ORIGINAL_
        # PENDING -> 1, 아니면 0). president_terms.is_current와 같은 패턴.
        sa.Column(
            "pending_priority",
            mysql.TINYINT(),
            sa.Computed("IF(status = 'ORIGINAL_PENDING', 1, 0)", persisted=False),
            nullable=False,
        ),
        sa.Column("issue_number", sa.CHAR(length=36), nullable=True),
        sa.Column("verification_token_hash", sa.String(length=64), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("pdf_object_key", sa.String(length=500), nullable=True),
        sa.Column("issued_at", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("deleted_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_number", name="uq_certificates_issue_number"),
    )
    # list_own의 WHERE user_id = ? ORDER BY created_at DESC, id DESC (+ 동일
    # 형태의 커서 술어)를 그대로 커버한다. user_id가 최좌측 컬럼이므로
    # user_id FK가 요구하는 커버 인덱스 역할도 대신한다.
    op.create_index(
        "idx_certificates_user_created_id",
        "certificates",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    # list_history의 ORDER BY pending_priority DESC, created_at DESC, id DESC
    # (+ 동일 형태의 커서 술어)를 그대로 커버한다.
    op.create_index(
        "idx_certificates_history_priority",
        "certificates",
        ["pending_priority", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "idx_certificates_created_at", "certificates", ["created_at"], unique=False
    )

    op.create_table(
        "certificate_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("certificate_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "APPLIED",
                "ISSUED",
                "DRAFT_CREATED",
                "ORIGINAL_REGISTERED",
                name="certificateeventaction",
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "APPLICANT",
                "SYSTEM",
                "PRESIDENT",
                "ADMIN",
                name="certificateactortype",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_id"], ["certificates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_certificate_events_certificate_created",
        "certificate_events",
        ["certificate_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # NOTE: idx_certificate_events_certificate_created and
    # idx_certificates_user_created_id (user_id가 최좌측 컬럼이므로 여전히
    # user_id FK를 커버한다) are each the *only* index covering their table's
    # FK column, so MySQL rejects an explicit DROP INDEX on them while the FK
    # constraint is still attached (error 1553). drop_table removes a table's
    # FKs and indexes together, so those two are intentionally left for
    # drop_table to clean up rather than dropped explicitly first.
    op.drop_table("certificate_events")

    op.drop_index("idx_certificates_created_at", table_name="certificates")
    op.drop_index("idx_certificates_history_priority", table_name="certificates")
    op.drop_table("certificates")
