import time

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Column,
    Computed,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    CertificateActorType,
    CertificateEventAction,
    CertificateKind,
    CertificateStatus,
)


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


class Certificate(Base, TimestampMixin, SoftDeleteMixin):
    """활동증명서 발급/신청 건.

    kind=SELF는 신청 즉시 발급 완료(issue_number 즉시 부여)되지만, kind=DRAFT는
    운영진이 초안만 만들고(issue_number NULL) 회장이 오프라인 서명본 원본을
    등록하는 시점에 issue_number가 부여되며 status가 ISSUED로 전환된다.
    """

    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    kind = Column(Enum(CertificateKind), nullable=False)
    status = Column(Enum(CertificateStatus), nullable=False)
    # 운영진용 발급 이력(list_history) 정렬 우선순위를 위한 생성 컬럼.
    # ORIGINAL_PENDING이면 1, 아니면 0. `status`를 저장할 때 DB 컬럼에는 (이
    # `Enum(CertificateStatus)`가 SQLAlchemy 기본 동작대로) 파이썬 enum의
    # `.value`가 아니라 `.name`(대문자, 마이그레이션의 `sa.Enum("ISSUED",
    # "ORIGINAL_PENDING", ...)`와 동일)이 들어가므로 아래 식도 대문자를 쓴다.
    # `app.services.certificate.CertificateService.list_history`가 이
    # 컬럼으로 정렬/커서 처리를 하고, `idx_certificates_history_priority`
    # (pending_priority, created_at, id) 인덱스가 그 쿼리 플랜을 커버한다.
    pending_priority = Column(
        TINYINT,
        Computed("IF(status = 'ORIGINAL_PENDING', 1, 0)", persisted=False),
        nullable=False,
    )

    # 발행번호 = str(uuid.uuid4()). 발급이 확정되기 전(DRAFT 초안 상태)에는 NULL.
    issue_number = Column(CHAR(36), nullable=True)
    # sha256 hex of a secrets.token_urlsafe(32) token; 향후 원본 대조 검증용.
    verification_token_hash = Column(String(64), nullable=True)

    options = Column(JSON, nullable=False)
    # 발급 시점의 렌더링 컨텍스트 스냅샷(90일 원본 대조용). 발급 전에는 NULL.
    snapshot = Column(JSON, nullable=True)

    pdf_object_key = Column(String(500), nullable=True)

    issued_at = Column(BigInteger, nullable=True)
    expires_at = Column(BigInteger, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    events = relationship(
        "CertificateEvent",
        back_populates="certificate",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # CertificateService.list_own의 WHERE user_id = ? ORDER BY created_at
        # DESC, id DESC (+ 동일 형태의 커서 술어)를 그대로 커버하는 복합
        # 인덱스. 이전의 단일 컬럼 idx_certificates_user_id는 이 정렬을
        # 커버하지 못해 filesort가 발생했다. user_id가 최좌측 컬럼이므로
        # user_id FK(ondelete=CASCADE)가 요구하는 커버 인덱스 역할도 그대로
        # 대신한다.
        Index("idx_certificates_user_created_id", "user_id", "created_at", "id"),
        # CertificateService.list_history의
        # ORDER BY pending_priority DESC, created_at DESC, id DESC (+ 동일
        # 형태의 커서 술어)를 그대로 커버하는 복합 인덱스. 이전의 단일 컬럼
        # idx_certificates_status는 이 쿼리의 어떤 WHERE/ORDER BY 절에서도
        # 참조되지 않아 실질적으로 죽은 인덱스였다.
        Index(
            "idx_certificates_history_priority",
            "pending_priority",
            "created_at",
            "id",
        ),
        Index("idx_certificates_created_at", "created_at"),
        # CertificateService.purge_all_expired의
        # WHERE expires_at IS NOT NULL AND expires_at < ? 범위 조건을 커버.
        # 스케줄러(app/scheduler.py)가 주기적으로 이 쿼리를 실행한다.
        Index("idx_certificates_expires_at", "expires_at"),
        UniqueConstraint("issue_number", name="uq_certificates_issue_number"),
    )


class CertificateEvent(Base):
    """활동증명서 처리 이력. append-only."""

    __tablename__ = "certificate_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    certificate_id = Column(
        Integer, ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False
    )
    action = Column(Enum(CertificateEventAction), nullable=False)
    actor_type = Column(Enum(CertificateActorType), nullable=False)
    actor_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))

    certificate = relationship("Certificate", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        Index(
            "idx_certificate_events_certificate_created",
            "certificate_id",
            "created_at",
        ),
    )
