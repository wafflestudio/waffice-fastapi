from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Computed,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    GraduationStatus,
    NotificationChannel,
    ProjectStatus,
    Qualification,
)


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Auth
    google_id = Column(String(255), unique=True, nullable=True)
    # Nullable so temporary members (imported from a roster, never logged in)
    # can exist without a real OAuth email. UNIQUE still holds because MySQL
    # permits multiple NULLs in a unique index.
    email = Column(String(255), nullable=True, unique=True)

    # Profile (required)
    name = Column(String(100), nullable=False)
    generation = Column(String(20), nullable=False, default="26")

    # Temporary member: created from an admin roster import with only name and
    # student_id populated. Has no email/OAuth identity until the real person
    # signs up. Distinct from qualification=PENDING (an OAuth signup awaiting
    # admin approval), which keeps the /users/pending flow uncluttered.
    is_temporary = Column(Boolean, nullable=False, default=False)

    # Status
    qualification = Column(
        Enum(Qualification), nullable=False, default=Qualification.PENDING
    )
    requested_qualification = Column(Enum(Qualification), nullable=True)
    privacy_policy_agreed = Column(Boolean, nullable=False, default=False)
    terms_agreed = Column(Boolean, nullable=False, default=False)
    marketing_agreed = Column(Boolean, nullable=False, default=False)
    is_leader = Column(Boolean, nullable=False, default=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_president = Column(Boolean, nullable=False, default=False)
    # `is_president`가 "현직 회장"의 진실 공급원이다 (`president_terms`는
    # 이 값이 바뀔 때마다 `PresidentService.appoint`/`step_down`이 남기는
    # 순수 이력 로그일 뿐, 더 이상 현직 판단에 쓰이지 않는다). 동시에 두 명
    # 이상이 회장일 수 없다는 불변식을, `PresidentTerm.is_current`가 쓰던
    # 것과 같은 생성 컬럼 + UNIQUE 인덱스 트릭으로 이 테이블에 직접 강제한다:
    # is_president가 false/NULL이면 이 컬럼도 NULL이라 유니크 인덱스가
    # 여러 명을 허용하지만, true인 사람은 최대 한 명만 허용된다.
    is_president_marker = Column(
        TINYINT,
        Computed("IF(is_president, 1, NULL)", persisted=False),
        nullable=True,
    )

    @property
    def has_admin_access(self) -> bool:
        """Admin-gated actions should check this, not is_admin directly.

        The president is the top of the org hierarchy and always has admin
        access, whether or not is_admin was also explicitly granted.
        """
        return self.is_admin or self.is_president

    @property
    def current_projects(self):
        return [
            m.project
            for m in self.project_memberships
            if m.left_at is None and m.project.status != ProjectStatus.ENDED
        ]

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
        Index("idx_users_is_leader", "is_leader"),
        Index("idx_users_is_admin", "is_admin"),
        Index("idx_users_is_president", "is_president"),
        Index("idx_users_created_at", "created_at"),
        Index("idx_users_is_temporary", "is_temporary"),
        # Roster import matches existing members by student_id.
        Index("idx_users_student_id", "student_id"),
        # (임시 비활성화 -- 재설계 전까지) "현직 회장은 동시에 한 명뿐" 제약.
        # 인수인계 기간 중 임기가 겹치는 경우나 잘못된 임명을 정정하는 경우를
        # 지원하기 위해 잠정적으로 풀어둔다. 재설계 시 다시 켤 수 있다.
        # UniqueConstraint("is_president_marker", name="uq_users_current_president"),
    )
