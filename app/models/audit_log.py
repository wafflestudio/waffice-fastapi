import time

from sqlalchemy import JSON, BigInteger, Column, Enum, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.enums import AuditAction


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    actor_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action = Column(Enum(AuditAction), nullable=False)
    payload = Column(JSON, nullable=False)

    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id])
    actor = relationship(
        "User", back_populates="acted_audit_logs", foreign_keys=[actor_id]
    )

    __table_args__ = (
        Index("idx_audit_logs_user_id", "user_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_created_at", "created_at"),
    )
