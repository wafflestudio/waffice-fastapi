from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import ProjectStatus


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(ProjectStatus), nullable=False, default=ProjectStatus.ACTIVE)

    started_at = Column(Date, nullable=False)
    ended_at = Column(Date, nullable=True)

    websites = Column(JSON, nullable=True)

    # Relationships
    members = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_projects_status", "status"),
        Index("idx_projects_created_at", "created_at"),
    )
