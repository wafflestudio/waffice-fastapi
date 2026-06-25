from sqlalchemy import JSON, BigInteger, Column, Enum, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    GraduationStatus,
    NotificationChannel,
    Qualification,
    UserRole,
)


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
    role = Column(Enum(UserRole), nullable=False, default=UserRole.MEMBER)

    @property
    def is_admin(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.ADMIN_AND_LEADER)

    @property
    def is_leader(self) -> bool:
        return self.role in (UserRole.LEADER, UserRole.ADMIN_AND_LEADER)

    # Profile (optional)
    phone = Column(String(20), nullable=True)
    affiliation = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    avatar_url = Column(String(500), nullable=True)

    # External links
    github_username = Column(String(100), nullable=True)
    slack_id = Column(String(100), nullable=True)
    websites = Column(JSON, nullable=True)
    graduation_status = Column(
        Enum(GraduationStatus), nullable=False, default=GraduationStatus.UNDERGRADUATE
    )

    # Academic / professional info
    student_id = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True)

    # Notification preferences
    contact_email = Column(String(255), nullable=True)
    notification_channel = Column(
        Enum(NotificationChannel),
        nullable=False,
        default=NotificationChannel.EMAIL,
    )

    # Relationships
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        foreign_keys="AuditLog.user_id",
        cascade="all, delete-orphan",
    )
    acted_audit_logs = relationship(
        "AuditLog",
        back_populates="actor",
        foreign_keys="AuditLog.actor_id",
    )
    project_memberships = relationship(
        "ProjectMember", back_populates="user", cascade="all, delete-orphan"
    )
    activities = relationship(
        "UserActivity", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_users_qualification", "qualification"),
        Index("idx_users_role", "role"),
        Index("idx_users_created_at", "created_at"),
    )
