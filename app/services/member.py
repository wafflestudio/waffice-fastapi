from __future__ import annotations

from datetime import date

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import HistoryAction, MemberRole, ProjectMember


class LastLeaderError(Exception):
    """Raised when trying to remove the last leader from a project"""

    pass


class CannotRemoveSelfError(Exception):
    """Raised when trying to remove oneself from a project"""

    pass


class MemberService:
    @staticmethod
    def get_active(db: Session, project_id: int, user_id: int) -> ProjectMember | None:
        """Get active membership for a user in a project"""
        return (
            db.query(ProjectMember)
            .filter(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.left_at.is_(None),
                )
            )
            .first()
        )

    @staticmethod
    def list_active(db: Session, project_id: int) -> list[ProjectMember]:
        """List all active members of a project"""
        return (
            db.query(ProjectMember)
            .filter(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.left_at.is_(None),
                )
            )
            .all()
        )

    @staticmethod
    def count_leaders(db: Session, project_id: int) -> int:
        """Count active leaders in a project"""
        return (
            db.query(ProjectMember)
            .filter(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role == MemberRole.LEADER,
                    ProjectMember.left_at.is_(None),
                )
            )
            .count()
        )

    @staticmethod
    def is_leader(db: Session, project_id: int, user_id: int) -> bool:
        """Check if a user is an active leader of a project"""
        return (
            db.query(ProjectMember)
            .filter(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.role == MemberRole.LEADER,
                    ProjectMember.left_at.is_(None),
                )
            )
            .first()
            is not None
        )

    @staticmethod
    def add(
        db: Session,
        project_id: int,
        user_id: int,
        role: MemberRole,
        position: str | None,
        actor_id: int,
    ) -> ProjectMember:
        """
        Add a member to a project (idempotent).
        If already an active member, returns existing membership without error.
        If new, creates membership and logs history.
        """
        # Check if already an active member (idempotency)
        existing = MemberService.get_active(db, project_id, user_id)
        if existing:
            return existing

        # Create new membership
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
            position=position,
            joined_at=date.today(),
            left_at=None,
        )
        db.add(member)
        db.flush()

        # Log history
        from app.models import Project
        from app.services.history import HistoryService

        project = db.query(Project).filter(Project.id == project_id).first()
        HistoryService.log(
            db=db,
            user_id=user_id,
            action=HistoryAction.PROJECT_JOINED,
            payload={
                "project_id": project_id,
                "project_name": project.name if project else "Unknown",
                "role": role.value,
                "position": position,
            },
            actor_id=actor_id,
        )

        # Note: caller should commit the transaction
        db.refresh(member)
        return member

    @staticmethod
    def remove(db: Session, member: ProjectMember, actor_id: int) -> None:
        """
        Remove a member from a project by setting left_at.
        Raises:
            LastLeaderError: If this is the last leader
            CannotRemoveSelfError: If actor is trying to remove themselves
        """
        # Check if last leader FIRST (more critical business rule)
        if member.role == MemberRole.LEADER:
            leader_count = MemberService.count_leaders(db, member.project_id)
            if leader_count <= 1:
                raise LastLeaderError("Cannot remove the last leader from project")

        # Check if trying to remove self
        if member.user_id == actor_id:
            raise CannotRemoveSelfError("Cannot remove self from project")

        # Set left_at
        member.left_at = date.today()
        db.flush()

        # Log history
        from app.models import Project
        from app.services.history import HistoryService

        project = db.query(Project).filter(Project.id == member.project_id).first()
        HistoryService.log(
            db=db,
            user_id=member.user_id,
            action=HistoryAction.PROJECT_LEFT,
            payload={
                "project_id": member.project_id,
                "project_name": project.name if project else "Unknown",
            },
            actor_id=actor_id,
        )
        # Note: caller should commit the transaction

    @staticmethod
    def change(
        db: Session,
        member: ProjectMember,
        role: MemberRole | None,
        position: str | None,
        actor_id: int,
    ) -> ProjectMember:
        """
        Change member role/position by ending current membership and creating new one.
        Logs history entry.

        Raises:
            LastLeaderError: If demoting the last leader to member role
        """
        old_role = member.role
        old_position = member.position
        new_role = role if role is not None else old_role

        # Check if demoting the last leader
        if old_role == MemberRole.LEADER and new_role == MemberRole.MEMBER:
            leader_count = MemberService.count_leaders(db, member.project_id)
            if leader_count <= 1:
                raise LastLeaderError("Cannot demote the last leader")

        # End current membership
        member.left_at = date.today()
        db.flush()

        # Create new membership
        new_member = ProjectMember(
            project_id=member.project_id,
            user_id=member.user_id,
            role=role if role is not None else old_role,
            position=position if position is not None else old_position,
            joined_at=date.today(),
            left_at=None,
        )
        db.add(new_member)
        db.flush()

        # Log history
        from app.services.history import HistoryService

        HistoryService.log(
            db=db,
            user_id=member.user_id,
            action=HistoryAction.PROJECT_ROLE_CHANGED,
            payload={
                "project_id": member.project_id,
                "from_role": old_role.value,
                "to_role": new_member.role.value,
                "from_position": old_position,
                "to_position": new_member.position,
            },
            actor_id=actor_id,
        )

        # Note: caller should commit the transaction
        db.refresh(new_member)
        return new_member
