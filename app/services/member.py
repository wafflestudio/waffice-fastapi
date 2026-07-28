from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ActivityStatus,
    AuditAction,
    MemberRole,
    Project,
    ProjectMember,
    User,
)

_UNSET = object()


class LastLeaderError(Exception):
    """Raised when trying to remove the last leader from a project"""

    pass


class CannotRemoveSelfError(Exception):
    """Raised when trying to remove oneself from a project"""

    pass


class MemberService:
    @staticmethod
    def list(
        db: Session,
        project_id: int,
        *,
        cursor: int | None = None,
        limit: int = 20,
        status: ActivityStatus | None = None,
        keyword: str | None = None,
    ) -> tuple[list[ProjectMember], int | None]:
        query = (
            db.query(ProjectMember)
            .options(joinedload(ProjectMember.user))
            .filter(ProjectMember.project_id == project_id)
        )
        if status == ActivityStatus.ACTIVE:
            query = query.filter(ProjectMember.left_at.is_(None))
        elif status == ActivityStatus.INACTIVE:
            query = query.filter(ProjectMember.left_at.is_not(None))
        if keyword is not None:
            pattern = f"%{keyword}%"
            query = query.join(ProjectMember.user).filter(
                or_(
                    User.name.ilike(pattern),
                    ProjectMember.position.ilike(pattern),
                    User.email.ilike(pattern),
                    User.github_username.ilike(pattern),
                )
            )
        if cursor is not None:
            query = query.filter(ProjectMember.id < cursor)

        members = query.order_by(ProjectMember.id.desc()).limit(limit + 1).all()
        has_more = len(members) > limit
        members = members[:limit]
        next_cursor = members[-1].id if has_more else None
        return members, next_cursor

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
    def sync_leader_flag(db: Session, user_id: int) -> None:
        """Sync the global leader flag from active project leaderships."""
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return
        user.is_leader = (
            db.query(ProjectMember.id)
            .join(Project, Project.id == ProjectMember.project_id)
            .filter(
                ProjectMember.user_id == user_id,
                ProjectMember.role == MemberRole.LEADER,
                ProjectMember.left_at.is_(None),
                Project.deleted_at.is_(None),
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
        if role == MemberRole.LEADER:
            MemberService.sync_leader_flag(db, user_id)

        # Log history
        from app.services.audit_log import AuditLogService

        project = db.query(Project).filter(Project.id == project_id).first()
        AuditLogService.log(
            db=db,
            user_id=user_id,
            action=AuditAction.PROJECT_JOINED,
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
        was_leader = member.role == MemberRole.LEADER
        if was_leader:
            leader_count = MemberService.count_leaders(db, member.project_id)
            if leader_count <= 1:
                raise LastLeaderError("Cannot remove the last leader from project")

        # Check if trying to remove self
        if member.user_id == actor_id:
            raise CannotRemoveSelfError("Cannot remove self from project")

        # Set left_at
        member.left_at = date.today()
        db.flush()
        if was_leader:
            MemberService.sync_leader_flag(db, member.user_id)

        # Log history
        from app.services.audit_log import AuditLogService

        project = db.query(Project).filter(Project.id == member.project_id).first()
        AuditLogService.log(
            db=db,
            user_id=member.user_id,
            action=AuditAction.PROJECT_LEFT,
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
        actor_id: int,
        role: MemberRole | None = None,
        position: str | None | object = _UNSET,
    ) -> ProjectMember:
        """
        Update the existing membership's role/position without changing its dates.
        Logs the change in audit history.

        Raises:
            LastLeaderError: If demoting the last leader to member role
        """
        old_role = member.role
        old_position = member.position
        new_role = role if role is not None else old_role
        new_position = old_position if position is _UNSET else position

        if old_role == new_role and old_position == new_position:
            # No change, return existing membership
            return member

        # Check if demoting the last leader
        if old_role == MemberRole.LEADER and new_role == MemberRole.MEMBER:
            leader_count = MemberService.count_leaders(db, member.project_id)
            if leader_count <= 1:
                raise LastLeaderError("Cannot demote the last leader")

        member.role = new_role
        member.position = new_position
        db.flush()
        if old_role != new_role:
            MemberService.sync_leader_flag(db, member.user_id)

        # Log history
        from app.services.audit_log import AuditLogService

        AuditLogService.log(
            db=db,
            user_id=member.user_id,
            action=AuditAction.PROJECT_ROLE_CHANGED,
            payload={
                "project_id": member.project_id,
                "from_role": old_role.value,
                "to_role": member.role.value,
                "from_position": old_position,
                "to_position": member.position,
            },
            actor_id=actor_id,
        )

        # Note: caller should commit the transaction
        db.refresh(member)
        return member
