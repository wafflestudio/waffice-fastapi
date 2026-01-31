from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import Qualification


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Auth
    google_id = Column(String(255), unique=True, nullable=True)
    email = Column(String(255), nullable=False, unique=True)

    # Profile (required)
    name = Column(String(100), nullable=False)
    generation = Column(String(20), nullable=False, default="26")

    # Status
    qualification = Column(
        Enum(Qualification), nullable=False, default=Qualification.PENDING
    )
    is_admin = Column(Boolean, nullable=False, default=False)

    # Profile (optional)
    phone = Column(String(20), nullable=True)
    affiliation = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String(500), nullable=True)

    # External links
    github_username = Column(String(100), nullable=True)
    slack_id = Column(String(100), nullable=True)
    websites = Column(JSON, nullable=True)

    # Relationships
    histories = relationship(
        "UserHistory",
        back_populates="user",
        foreign_keys="UserHistory.user_id",
        cascade="all, delete-orphan",
    )
    acted_histories = relationship(
        "UserHistory",
        back_populates="actor",
        foreign_keys="UserHistory.actor_id",
    )
    project_memberships = relationship(
        "ProjectMember", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_users_qualification", "qualification"),
        Index("idx_users_is_admin", "is_admin"),
        Index("idx_users_created_at", "created_at"),
    )
