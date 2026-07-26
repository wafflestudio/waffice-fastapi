from __future__ import annotations

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.exceptions import (
    CannotRemoveSelfError,
    InvalidProjectMemberFileError,
    LastLeaderError,
)
from app.models import (
    ActivityStatus,
    MemberRole,
    Project,
    ProjectMember,
    ProjectStatus,
    Qualification,
    User,
    UserActivity,
)
from app.services.member import (
    CannotRemoveSelfError as ServiceCannotRemoveSelfError,
    LastLeaderError as ServiceLastLeaderError,
    MemberService,
)
from app.services.roster import MultiProjectMemberRosterRow, ProjectMemberRosterRow


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
    def replace_members_by_project_name(
        db: Session,
        rows: list[MultiProjectMemberRosterRow],
        actor_id: int,
    ) -> list[Project]:
        """
        Group rows by project name and atomically replace each named
        project's active member roster to match the file (add/update/
        remove) — the same full-replace semantics as replace_members,
        applied to every project referenced in a single multi-project
        upload.

        Members are matched by student ID against qualification=ACTIVE
        users only (활동회원). A new membership opens a UserActivity record
        (position carried over as-is, start date today, still ongoing); a
        membership that ends closes out any open UserActivity for that
        (user, project) pair. Memberships that persist in both the old and
        new roster are left untouched (no change to their active period).

        Every project referenced in the file is validated before any writes
        happen: an error anywhere in the file aborts the entire upload with
        no changes made.
        """
        import time

        rows_by_project_name: dict[str, list[MultiProjectMemberRosterRow]] = {}
        for row in rows:
            rows_by_project_name.setdefault(row.project_name, []).append(row)

        projects_by_name: dict[str, list[Project]] = {}
        for project in (
            db.query(Project)
            .filter(
                Project.deleted_at.is_(None),
                Project.name.in_(rows_by_project_name.keys()),
            )
            .all()
        ):
            projects_by_name.setdefault(project.name, []).append(project)

        student_ids = {row.student_id for row in rows}
        users_by_student_id: dict[str, list[User]] = {}
        for user in (
            db.query(User)
            .filter(
                User.deleted_at.is_(None),
                User.qualification == Qualification.ACTIVE,
                User.student_id.in_(student_ids),
            )
            .all()
        ):
            users_by_student_id.setdefault(user.student_id, []).append(user)

        errors: list[dict] = []
        groups: dict[
            int,
            tuple[
                list[tuple[MultiProjectMemberRosterRow, User]],
                dict[int, ProjectMember],
            ],
        ] = {}

        for project_name, group_rows in rows_by_project_name.items():
            matches = projects_by_name.get(project_name, [])
            if not matches:
                errors.append(
                    _member_file_error(
                        group_rows[0].row_number,
                        "프로젝트명",
                        "project_not_found",
                        f"{project_name} 프로젝트명을 찾을 수 없습니다. " "프로젝트 목록에 존재하는지 확인해주세요.",
                    )
                )
                continue
            if len(matches) > 1:
                errors.append(
                    _member_file_error(
                        group_rows[0].row_number,
                        "프로젝트명",
                        "ambiguous_project_name",
                        f"{project_name} 프로젝트명을 가진 프로젝트가 여러 개입니다. " "운영팀에 문의해주세요.",
                    )
                )
                continue
            project = matches[0]

            resolved: list[tuple[MultiProjectMemberRosterRow, User]] = []
            seen_user_ids: set[int] = set()
            for row in group_rows:
                user_matches = users_by_student_id.get(row.student_id, [])
                if not user_matches:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            "학번",
                            "user_not_found",
                            f"{row.name}({row.student_id})을 활동회원 명부에서 찾을 수 없습니다.",
                        )
                    )
                    continue
                if len(user_matches) > 1:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            "학번",
                            "ambiguous_student_id",
                            "같은 학번을 가진 활동회원이 여러 명입니다. 운영팀에 문의해주세요.",
                        )
                    )
                    continue
                user = user_matches[0]
                if user.name != row.name:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            "프로젝트원 이름",
                            "name_mismatch",
                            f"파일의 데이터({row.name}, {row.student_id})가 DB의 데이터"
                            f"({user.name}, {row.student_id})와 일치하지 않습니다. "
                            "오타를 확인해주세요.",
                        )
                    )
                    continue
                if user.id in seen_user_ids:
                    errors.append(
                        _member_file_error(
                            row.row_number,
                            "학번",
                            "duplicate_user",
                            "같은 프로젝트에 같은 회원이 파일에 두 번 이상 포함되어 있습니다.",
                        )
                    )
                    continue
                seen_user_ids.add(user.id)
                resolved.append((row, user))

            if resolved and not any(row.is_leader for row, _ in resolved):
                errors.append(
                    _member_file_error(
                        group_rows[0].row_number,
                        "팀장 여부",
                        "no_leader",
                        f"{project_name} 프로젝트에는 팀장이 한 명 이상 있어야 합니다.",
                    )
                )

            current_by_user_id = {
                member.user_id: member
                for member in MemberService.list_active(db, project.id)
            }
            target_user_ids = {user.id for _, user in resolved}
            if actor_id in current_by_user_id and actor_id not in target_user_ids:
                errors.append(
                    _member_file_error(
                        group_rows[0].row_number,
                        "학번",
                        "cannot_remove_self",
                        f"{project_name} 프로젝트에서 자기 자신을 제외할 수 없습니다.",
                    )
                )

            groups[project.id] = (resolved, current_by_user_id)

        if errors:
            raise InvalidProjectMemberFileError(errors)

        now = int(time.time())
        try:
            for project_id, (resolved, current_by_user_id) in groups.items():
                target_by_user_id = {user.id: row for row, user in resolved}

                for row, user in resolved:
                    if user.id not in current_by_user_id:
                        MemberService.add(
                            db,
                            project_id=project_id,
                            user_id=user.id,
                            role=(
                                MemberRole.LEADER
                                if row.is_leader
                                else MemberRole.MEMBER
                            ),
                            position=row.position,
                            actor_id=actor_id,
                        )
                        db.add(
                            UserActivity(
                                user_id=user.id,
                                project_id=project_id,
                                position=row.position or "",
                                start_date=now,
                                end_date=None,
                                status=ActivityStatus.ACTIVE,
                            )
                        )
                        db.flush()

                changes = [
                    (member, target_by_user_id[user_id])
                    for user_id, member in current_by_user_id.items()
                    if user_id in target_by_user_id
                    and (
                        member.role
                        != (
                            MemberRole.LEADER
                            if target_by_user_id[user_id].is_leader
                            else MemberRole.MEMBER
                        )
                        or member.position != target_by_user_id[user_id].position
                    )
                ]
                changes.sort(key=lambda item: not item[1].is_leader)
                for member, row in changes:
                    MemberService.change(
                        db,
                        member=member,
                        actor_id=actor_id,
                        role=MemberRole.LEADER if row.is_leader else MemberRole.MEMBER,
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
                    open_activities = (
                        db.query(UserActivity)
                        .filter(
                            UserActivity.user_id == member.user_id,
                            UserActivity.project_id == project_id,
                            UserActivity.end_date.is_(None),
                        )
                        .all()
                    )
                    for activity in open_activities:
                        activity.end_date = now
                        activity.status = ActivityStatus.INACTIVE
                    db.flush()
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

        return [
            ProjectService.get_with_members(db, project_id) for project_id in groups
        ]

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
        """Soft delete a project by setting deleted_at"""
        import time

        project.deleted_at = int(time.time())
        db.commit()


def _member_file_error(row: int, field: str, code: str, message: str) -> dict:
    return {"row": row, "field": field, "code": code, "message": message}
