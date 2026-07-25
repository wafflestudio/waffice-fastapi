from sqlalchemy import (
    Column,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import TimestampMixin


class PresidentTerm(Base, TimestampMixin):
    """회장 임기.

    (임시 비활성화 -- 재설계 전까지) 원래는 "동시에 열린 임기는 최대 하나"를
    `is_current` 생성 컬럼 + UNIQUE 인덱스로 DB 레벨에서 강제했으나, 인수인계
    기간 중 임기가 겹치는 경우나 잘못 입력한 임명을 더 이른 날짜로 정정하는
    경우를 지원하기 위해 잠정적으로 그 제약을 풀어둔다 (아래 `__table_args__`
    주석 처리 및 migration 참고). 재설계 시 다시 켤 수 있도록 코드는 남겨둔다.
    """

    __tablename__ = "president_terms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    started_at = Column(Date, nullable=False)
    ended_at = Column(Date, nullable=True)

    is_current = Column(
        TINYINT,
        Computed("IF(ended_at IS NULL, 1, NULL)", persisted=False),
        nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("idx_president_terms_user_id", "user_id"),
        # (임시 비활성화) "열린 임기는 최대 하나" 제약. 클래스 docstring 참고.
        # UniqueConstraint("is_current", name="uq_president_current"),
    )
