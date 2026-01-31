from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from app.models import Project, ProjectMember, ProjectStatus


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
        query = db.query(Project).filter(Project.deleted_at.is_(None))

        if status is not None:
            query = query.filter(Project.status == status)

        if cursor is not None:
            query = query.filter(Project.created_at < cursor)

        query = query.order_by(Project.created_at.desc()).limit(limit + 1)
        projects = query.all()

        has_more = len(projects) > limit
        if has_more:
            projects = projects[:limit]

        next_cursor = projects[-1].created_at if has_more and projects else None
        return projects, next_cursor

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
        """Create a new project"""
        project = Project(**data)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def update(db: Session, project: Project, **data) -> Project:
        """Update project with provided data"""
        for key, value in data.items():
            if value is not None:
                setattr(project, key, value)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def delete(db: Session, project: Project) -> None:
        """Soft delete a project by setting deleted_at"""
        import time

        project.deleted_at = int(time.time())
        db.commit()
