from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import TimestampMixin


class CertificateSignature(Base, TimestampMixin):
    """회장 서명 이미지(PNG). 회장 1인당 서명 1개만 등록 가능."""

    __tablename__ = "certificate_signatures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    object_key = Column(String(500), nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_certificate_signatures_user_id"),
    )
