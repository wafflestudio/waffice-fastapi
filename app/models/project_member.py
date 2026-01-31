from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import TimestampMixin
from app.models.enums import MemberRole


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    role = Column(Enum(MemberRole), nullable=False)
    position = Column(String(50), nullable=True)

    joined_at = Column(Date, nullable=True)
    left_at = Column(Date, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships")

    __table_args__ = (
        Index("idx_members_project", "project_id"),
        Index("idx_members_user", "user_id"),
        Index("idx_members_active", "project_id", "user_id", "left_at"),
    )
