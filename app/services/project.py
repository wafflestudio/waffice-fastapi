from __future__ import annotations

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    CannotRemoveSelfError,
    InvalidProjectMemberFileError,
    LastLeaderError,
    NotFoundError,
    ProjectHasPendingRequestsError,
)
from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    MemberRole,
    Project,
    ProjectMember,
    ProjectStatus,
    User,
)
from app.services.member import (
    CannotRemoveSelfError as ServiceCannotRemoveSelfError,
    LastLeaderError as ServiceLastLeaderError,
    MemberService,
)
from app.services.roster import ProjectMemberRosterRow


class ProjectService:
    @staticmethod
    def get(db: Session, project_id: int) -> Project | None:
        """Get project by ID (excluding soft-deleted projects)"""
        return (
            db.query(Project)
            .filter(and_(Project.id == project_id, Project.deleted_at.is_(None)))
            .first()
        )

    @staticmethod
    def get_with_members(db: Session, project_id: int) -> Project | None:
        """Get project with members loaded (excluding soft-deleted projects)"""
        return (
            db.query(Project)
            .options(joinedload(Project.members).joinedload(ProjectMember.user))
            .filter(and_(Project.id == project_id, Project.deleted_at.is_(None)))
            .first()
        )

    @staticmethod
    def list(
        db: Session,
        *,
        cursor: int | None = None,
        limit: int = 20,
        status: ProjectStatus | None = None,
    ) -> tuple[list[Project], int | None]:
        """
        List projects with cursor-based pagination (excluding soft-deleted projects).
        Returns (items, next_cursor)
        """
        query = (
            db.query(Project)
            .options(
                joinedload(
                    Project.members.and_(ProjectMember.left_at.is_(None))
                ).joinedload(ProjectMember.user)
            )
            .filter(Project.deleted_at.is_(None))
        )

        if status is not None:
            query = query.filter(Project.status == status)

        if cursor is not None:
            query = query.filter(Project.id < cursor)

        query = query.order_by(Project.id.desc()).limit(limit + 1)
        projects = query.all()

        has_more = len(projects) > limit
        if has_more:
            projects = projects[:limit]

        next_cursor = projects[-1].id if has_more and projects else None
        return projects, next_cursor

    @staticmethod
    def replace_members(
        db: Session,
        project_id: int,
        rows: list[ProjectMemberRosterRow],
        actor_id: int,
    ) -> Project:
        """Resolve and atomically replace the project's active member roster."""
        emails = {row.email for row in rows if row.email}
        student_ids = {row.student_id for row in rows if row.student_id}
        conditions = []
        if emails:
            conditions.append(func.lower(User.email).in_(emails))
        if student_ids:
            conditions.append(User.student_id.in_(student_ids))
        users = db.query(User).filter(User.deleted_at.is_(None), or_(*conditions)).all()
        users_by_email = {user.email.lower(): user for user in users if user.email}
        users_by_student_id: dict[str, list[User]] = {}
        for user in users:
            if user.student_id:
                users_by_student_id.setdefault(user.student_id, []).append(user)

        errors = []
        resolved: list[tuple[ProjectMemberRosterRow, User]] = []
        seen_user_ids: set[int] = set()
        for row in rows:
            user = None
            field = "이메일" if row.email else "학번"
            if row.email:
                user = users_by_email.get(row.email)
                if user is None:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            field,
                            "user_not_found",
                            "이메일에 해당하는 회원을 찾을 수 없습니다.",
                        )
                    )
                elif row.student_id and user.student_id != row.student_id:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            "학번",
                            "identifier_mismatch",
                            "이메일과 학번이 서로 다른 회원을 가리킵니다.",
                        )
                    )
            else:
                matches = users_by_student_id.get(row.student_id, [])
                if len(matches) == 1:
                    user = matches[0]
                elif not matches:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            field,
                            "user_not_found",
                            "학번에 해당하는 회원을 찾을 수 없습니다.",
                        )
                    )
                else:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            field,
                            "ambiguous_student_id",
                            "같은 학번을 가진 회원이 여러 명입니다.",
                        )
                    )

            if user is None:
                continue
            if user.id in seen_user_ids:
                errors.append(
                    _member_file_error(
                        row.row_number,
                        field,
                        "duplicate_user",
                        "같은 회원이 파일에 두 번 이상 포함되어 있습니다.",
                    )
                )
            else:
                seen_user_ids.add(user.id)
                resolved.append((row, user))

        if not errors and not any(row.role == MemberRole.LEADER for row, _ in resolved):
            errors.append(
                _member_file_error(
                    1,
                    "역할",
                    "no_leader",
                    "프로젝트에는 팀장이 한 명 이상 있어야 합니다.",
                )
            )
        if errors:
            raise InvalidProjectMemberFileError(errors)

        current_by_user_id = {
            member.user_id: member
            for member in MemberService.list_active(db, project_id)
        }
        target_by_user_id = {user.id: row for row, user in resolved}
        if actor_id in current_by_user_id and actor_id not in target_by_user_id:
            raise CannotRemoveSelfError()

        try:
            for row, user in resolved:
                if user.id not in current_by_user_id:
                    MemberService.add(
                        db,
                        project_id=project_id,
                        user_id=user.id,
                        role=row.role,
                        position=row.position,
                        actor_id=actor_id,
                    )

            changes = [
                (member, target_by_user_id[user_id])
                for user_id, member in current_by_user_id.items()
                if user_id in target_by_user_id
                and (
                    member.role != target_by_user_id[user_id].role
                    or member.position != target_by_user_id[user_id].position
                )
            ]
            changes.sort(key=lambda item: item[1].role != MemberRole.LEADER)
            for member, row in changes:
                MemberService.change(
                    db,
                    member=member,
                    actor_id=actor_id,
                    role=row.role,
                    position=row.position,
                )

            removed = [
                member
                for user_id, member in current_by_user_id.items()
                if user_id not in target_by_user_id
            ]
            removed.sort(key=lambda member: member.role == MemberRole.LEADER)
            for member in removed:
                MemberService.remove(db, member=member, actor_id=actor_id)
            db.commit()
        except ServiceLastLeaderError:
            db.rollback()
            raise LastLeaderError()
        except ServiceCannotRemoveSelfError:
            db.rollback()
            raise CannotRemoveSelfError()
        except Exception:
            db.rollback()
            raise

        return ProjectService.get_with_members(db, project_id)

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[Project]:
        """List all active projects that a user is a member of"""
        return (
            db.query(Project)
            .join(ProjectMember)
            .filter(
                and_(
                    ProjectMember.user_id == user_id,
                    ProjectMember.left_at.is_(None),
                    Project.deleted_at.is_(None),
                )
            )
            .order_by(Project.created_at.desc())
            .all()
        )

    @staticmethod
    def create(db: Session, **data) -> Project:
        """Create a new project. Call db.commit() after to persist."""
        project = Project(**data)
        if project.ended_at is not None:
            project.status = ProjectStatus.ENDED
        db.add(project)
        db.flush()
        db.refresh(project)
        return project

    @staticmethod
    def update(db: Session, project: Project, **data) -> Project:
        """Update project with provided data"""
        for key, value in data.items():
            if value is not None:
                setattr(project, key, value)
        if project.ended_at is not None and project.status != ProjectStatus.ENDED:
            project.status = ProjectStatus.ENDED
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def delete(db: Session, project: Project) -> None:
        """Soft delete a project unless it has a pending approval request."""
        import time

        locked_project = (
            db.query(Project)
            .filter(
                and_(
                    Project.id == project.id,
                    Project.deleted_at.is_(None),
                )
            )
            .populate_existing()
            .with_for_update()
            .first()
        )
        if locked_project is None:
            raise NotFoundError("Project not found")

        pending_request_exists = (
            db.query(ApprovalRequest.id)
            .filter(
                and_(
                    ApprovalRequest.project_id == locked_project.id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                    ApprovalRequest.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )
        if pending_request_exists:
            raise ProjectHasPendingRequestsError()

        locked_project.deleted_at = int(time.time())
        db.commit()


def _member_file_error(row: int, field: str, code: str, message: str) -> dict:
    return {"row": row, "field": field, "code": code, "message": message}
