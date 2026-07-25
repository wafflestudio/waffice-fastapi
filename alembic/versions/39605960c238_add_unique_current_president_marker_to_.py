"""add current-president marker column to users (no unique constraint)

Revision ID: 39605960c238
Revises: 3b02e9b6b13d
Create Date: 2026-07-25 01:05:26.068322

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "39605960c238"
down_revision: Union[str, None] = "3b02e9b6b13d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """`is_president_marker`만 추가한다 (유니크 제약은 안 건다).

    "회장은 동시에 한 명뿐"을 여기서 유니크 제약으로 강제하려 했으나,
    인수인계 기간 중 임기가 겹치는 경우나 잘못된 임명 정정을 지원하기 위해
    이 마이그레이션 계열에서 그 제약을 아예 걸지 않기로 했다 (관련
    `app/models/user.py`의 주석 처리된 `UniqueConstraint` 참고). 이 컬럼에
    유니크 제약을 걸면, 이미 `is_president=True`인 유저가 2명 이상 있는
    환경에서 이 마이그레이션 자체가 중복키 에러로 실패해 배포가 막힌다 --
    실제로 dev 환경에서 이 문제로 앱이 CrashLoopBackOff에 빠졌다. 재설계
    후 제약을 다시 걸고 싶으면 데이터 정합성(중복 회장)부터 정리한 뒤 별도
    마이그레이션으로 추가해야 한다.
    """
    op.add_column(
        "users",
        sa.Column(
            "is_president_marker",
            mysql.TINYINT(),
            sa.Computed("IF(is_president, 1, NULL)", persisted=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_president_marker")
