"""temporarily drop single-current-president constraint on president_terms

Revision ID: 8af105d95228
Revises: 39605960c238
Create Date: 2026-07-25 18:08:08.666031

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8af105d95228"
down_revision: Union[str, None] = "39605960c238"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ "현직 회장은 동시에 한 명뿐" 제약을 잠정적으로 해제한다.

    인수인계 기간 중 임기가 겹치는 경우나, 잘못된 임명을 더 이른 날짜로
    정정해야 하는 경우를 지원하기 위한 임시 조치. `is_current` 생성 컬럼
    자체는 남겨두고 유니크 제약만 지운다 -- 재설계 후 다시 추가할 수
    있도록. (`users.is_president_marker`는 애초에 유니크 제약 없이
    추가됐으므로 -- `39605960c238` 참고 -- 여기서 지울 게 없다.)

    존재 여부를 먼저 확인하고 있을 때만 지운다: 어떤 환경에서 이 마이그레이션
    계열이 절반만 적용된 상태로 남아있어 이미 지워져 있거나, 애초에 다른
    경로로 없어졌을 가능성에 대비한 방어적 처리.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_constraints = {
        uc["name"] for uc in inspector.get_unique_constraints("president_terms")
    }
    if "uq_president_current" in existing_constraints:
        op.drop_constraint("uq_president_current", "president_terms", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_president_current", "president_terms", ["is_current"]
    )
