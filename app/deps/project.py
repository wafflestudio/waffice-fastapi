from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Project, User
from app.services import MemberService, ProjectService


def require_leader_or_admin(project_id: int, user: User, db: Session) -> Project:
    """
    Require user to be either an admin or a leader of the project.
    Returns the project if authorized, raises 403 otherwise.
    """
    # Admin has full access
    if user.is_admin:
        project = ProjectService.get(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )
        return project

    # Check if user is a leader of this project
    if MemberService.is_leader(db, project_id, user.id):
        project = ProjectService.get(db, project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
            )
        return project

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only project leaders or admins can modify this project",
    )
