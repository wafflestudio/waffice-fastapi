from sqlalchemy import JSON, BigInteger, Column, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import ApprovalStatus


class ApprovalRequest(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    requester_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reviewed_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    status = Column(
        Enum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    body = Column(JSON, nullable=False)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(BigInteger, nullable=True)

    reviewers = relationship(
        "RequestReviewer",
        back_populates="approval_request",
        cascade="all, delete-orphan",
    )
    project = relationship("Project", foreign_keys=[project_id])
    requester = relationship("User", foreign_keys=[requester_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    __table_args__ = (
        Index("idx_approval_requests_status", "status"),
        Index("idx_approval_requests_created_at", "created_at"),
        Index("idx_approval_requests_project_id", "project_id"),
        Index("idx_approval_requests_requester_id", "requester_id"),
        Index("idx_approval_requests_reviewed_by_id", "reviewed_by_id"),
    )


class RequestReviewer(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "request_reviewers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    approval_request_id = Column(
        Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )

    approval_request = relationship(
        "ApprovalRequest",
        back_populates="reviewers",
        foreign_keys=[approval_request_id],
    )
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("idx_request_reviewers_approval_request_id", "approval_request_id"),
        Index("idx_request_reviewers_user_id", "user_id"),
        Index(
            "idx_request_reviewers_request_user",
            "approval_request_id",
            "user_id",
            unique=True,
        ),
    )
