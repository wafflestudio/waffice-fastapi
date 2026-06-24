import time

from sqlalchemy import (
    BigInteger,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.enums import ActivityStatus


class UserActivity(Base):
    __tablename__ = "user_activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    position = Column(String(100), nullable=False)
    start_date = Column(BigInteger, nullable=False)
    end_date = Column(BigInteger, nullable=True)
    status = Column(Enum(ActivityStatus), nullable=False, default=ActivityStatus.ACTIVE)
    description = Column(Text, nullable=True)

    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )

    user = relationship("User", back_populates="activities")
    project = relationship("Project")

    @property
    def project_name(self) -> str | None:
        return self.project.name if self.project else None

    __table_args__ = (
        Index("idx_activities_user_id", "user_id"),
        Index("idx_activities_project_id", "project_id"),
    )
