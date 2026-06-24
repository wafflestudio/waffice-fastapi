from sqlalchemy import Column, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship

from app.config.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin
from app.models.enums import ApprovalActionType, ApprovalStatus


class ApprovalRequest(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requester_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    status = Column(
        Enum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    action_type = Column(Enum(ApprovalActionType), nullable=False)
    body = Column(Text, nullable=True)

    approvers = relationship(
        "Approver",
        back_populates="approval_request",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_approval_requests_status", "status"),
        Index("idx_approval_requests_created_at", "created_at"),
        Index("idx_approval_requests_action_type", "action_type"),
    )


class Approver(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "approvers"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    approval_request_id = Column(
        Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )

    approval_request = relationship(
        "ApprovalRequest",
        back_populates="approvers",
        foreign_keys=[approval_request_id],
    )

    __table_args__ = (
        Index("idx_approvers_approval_request_id", "approval_request_id"),
        Index("idx_approvers_user_id", "user_id"),
        Index("idx_approvers_project_id", "project_id"),
        Index(
            "idx_approvers_request_user",
            "approval_request_id",
            "user_id",
            unique=True,
        ),
    )
