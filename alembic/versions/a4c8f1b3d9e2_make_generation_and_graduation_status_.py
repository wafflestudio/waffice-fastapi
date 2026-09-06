"""make generation and graduation_status nullable

Revision ID: a4c8f1b3d9e2
Revises: f8a3c1d92b6e
Create Date: 2026-09-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c8f1b3d9e2"
down_revision: Union[str, None] = "f8a3c1d92b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRADUATION_STATUS_ENUM = sa.Enum(
    "UNDERGRADUATE",
    "GRADUATED",
    "LEAVE_OF_ABSENCE",
    "GRADUATE_STUDENT",
    name="graduationstatus",
)


def upgrade() -> None:
    # 활동회원 명부 일괄 갱신 시 생성되는 임시 회원의 기수/학적상태를 파일에
    # 값이 없으면 "26"/"학부생" 같은 실제 값처럼 보이는 기본값 대신 NULL로
    # 남겨두기 위해 두 컬럼을 nullable로 바꾼다.
    op.alter_column(
        "users",
        "generation",
        existing_type=sa.String(length=20),
        nullable=True,
    )
    op.alter_column(
        "users",
        "graduation_status",
        existing_type=_GRADUATION_STATUS_ENUM,
        nullable=True,
    )


def downgrade() -> None:
    # NOT NULL로 되돌리기 전에, 그 사이 생성됐을 NULL 값을 기존 기본값으로
    # 채워야 ALTER가 실패하지 않는다.
    op.execute("UPDATE users SET generation = '26' WHERE generation IS NULL")
    op.execute(
        "UPDATE users SET graduation_status = 'UNDERGRADUATE' "
        "WHERE graduation_status IS NULL"
    )
    op.alter_column(
        "users",
        "generation",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "users",
        "graduation_status",
        existing_type=_GRADUATION_STATUS_ENUM,
        nullable=False,
    )
