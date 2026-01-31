import time

from sqlalchemy import JSON, BigInteger, Column, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.enums import HistoryAction


class UserHistory(Base):
    __tablename__ = "user_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    actor_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action = Column(Enum(HistoryAction), nullable=False)
    payload = Column(JSON, nullable=False)

    # Timestamp (no updated_at since this is immutable data)
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    # Relationships
    user = relationship("User", back_populates="histories", foreign_keys=[user_id])
    actor = relationship(
        "User", back_populates="acted_histories", foreign_keys=[actor_id]
    )

    __table_args__ = (
        Index("idx_histories_user_id", "user_id"),
        Index("idx_histories_action", "action"),
        Index("idx_histories_created_at", "created_at"),
    )
