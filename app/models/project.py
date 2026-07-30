from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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

    # True for exactly one project: the "운영팀" (admin team). Its active
    # members drive User.is_admin and its leader(s) drive User.is_president --
    # see ProjectService.sync_admin_team_roles. Never set via any API; only
    # ever assigned by the bootstrap migration.
    is_admin_team = Column(Boolean, nullable=False, default=False)

    # Relationships
    members = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_projects_status", "status"),
        Index("idx_projects_created_at", "created_at"),
    )
