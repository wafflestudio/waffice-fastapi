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

    현직 회장 = ended_at IS NULL인 행. 동시에 두 개 이상의 임기가 열려 있으면
    안 되므로, MySQL 8 생성 컬럼(is_current)과 UNIQUE 인덱스로 이 불변식을 DB
    레벨에서 강제한다: ended_at이 NULL이면 is_current=1, 그렇지 않으면 NULL이
    되고 MySQL의 UNIQUE 인덱스는 NULL끼리 충돌하지 않으므로 종료된 임기는 여러
    개 허용되지만 열린 임기는 최대 하나만 허용된다.
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
        UniqueConstraint("is_current", name="uq_president_current"),
    )
