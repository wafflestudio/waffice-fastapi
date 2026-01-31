from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_admin, require_regular
from app.deps.project import require_leader_or_admin
from app.exceptions import (
    CannotRemoveSelfError,
    LastLeaderError,
    NoLeaderError,
    NotFoundError,
)
from app.models import MemberRole, User
from app.schemas import (
    CursorPage,
    MemberInput,
    MemberUpdateRequest,
    ProjectBrief,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectUpdateRequest,
    Response,
)
from app.services import MemberService, ProjectService, UserService
from app.services.member import (
    CannotRemoveSelfError as ServiceCannotRemoveSelfError,
    LastLeaderError as ServiceLastLeaderError,
)

router = APIRouter()


@router.get("", response_model=Response[CursorPage[ProjectBrief]])
async def list_projects(
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """List all projects with cursor pagination (requires regular or higher)"""
    projects, next_cursor = ProjectService.list(db, cursor=cursor, limit=limit)
    return Response(ok=True, data=CursorPage(items=projects, next_cursor=next_cursor))


@router.post("", response_model=Response[ProjectDetail])
async def create_project(
    request: ProjectCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new project (admin only)"""
    # Validate: at least one leader is required
    has_leader = any(m.role == MemberRole.LEADER for m in request.members)
    if not has_leader:
        raise NoLeaderError()

    # Create project
    project_data = request.model_dump(exclude={"members"})
    project = ProjectService.create(db, **project_data)

    # Add members
    for member_input in request.members:
        # Verify user exists
        user = UserService.get(db, member_input.user_id)
        if not user:
            raise NotFoundError(f"User {member_input.user_id} not found")

        MemberService.add(
            db=db,
            project_id=project.id,
            user_id=member_input.user_id,
            role=member_input.role,
            position=member_input.position,
            actor_id=admin.id,
        )

    # Reload project with members
    project = ProjectService.get_with_members(db, project.id)
    return Response(ok=True, data=project)


@router.get("/{project_id}", response_model=Response[ProjectDetail])
async def get_project(
    project_id: int,
    _user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """Get project detail (requires regular or higher)"""
    project = ProjectService.get_with_members(db, project_id)
    if not project:
        raise NotFoundError("Project not found")
    return Response(ok=True, data=project)


@router.patch("/{project_id}", response_model=Response[ProjectDetail])
async def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """Update project (requires leader or admin)"""
    # Check permission
    project = require_leader_or_admin(project_id, user, db)

    # Update project
    update_data = request.model_dump(exclude_unset=True)
    project = ProjectService.update(db, project, **update_data)

    # Reload with members
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.delete("/{project_id}", response_model=Response[None])
async def delete_project(
    project_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete project (soft delete, admin only)"""
    project = ProjectService.get(db, project_id)
    if not project:
        raise NotFoundError("Project not found")

    ProjectService.delete(db, project)
    return Response(ok=True, message="Project deleted successfully")


# === Project Members ===
@router.post("/{project_id}/members", response_model=Response[ProjectDetail])
async def add_project_member(
    project_id: int,
    member_input: MemberInput,
    user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Add member to project (requires leader or admin).
    Idempotent: returns existing member if already active.
    """
    # Check permission
    require_leader_or_admin(project_id, user, db)

    # Verify user exists
    target_user = UserService.get(db, member_input.user_id)
    if not target_user:
        raise NotFoundError(f"User {member_input.user_id} not found")

    # Add member (idempotent)
    MemberService.add(
        db=db,
        project_id=project_id,
        user_id=member_input.user_id,
        role=member_input.role,
        position=member_input.position,
        actor_id=user.id,
    )

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.patch("/{project_id}/members/{user_id}", response_model=Response[ProjectDetail])
async def update_project_member(
    project_id: int,
    user_id: int,
    request: MemberUpdateRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """Update member role/position (requires leader or admin)"""
    # Check permission
    require_leader_or_admin(project_id, current_user, db)

    # Get member
    member = MemberService.get_active(db, project_id, user_id)
    if not member:
        raise NotFoundError("Member not found in this project")

    # Update member
    MemberService.change(
        db=db,
        member=member,
        role=request.role,
        position=request.position,
        actor_id=current_user.id,
    )

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.delete(
    "/{project_id}/members/{user_id}", response_model=Response[ProjectDetail]
)
async def remove_project_member(
    project_id: int,
    user_id: int,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """Remove member from project (requires leader or admin)"""
    # Check permission
    require_leader_or_admin(project_id, current_user, db)

    # Get member
    member = MemberService.get_active(db, project_id, user_id)
    if not member:
        raise NotFoundError("Member not found in this project")

    # Remove member
    try:
        MemberService.remove(db=db, member=member, actor_id=current_user.id)
    except ServiceLastLeaderError:
        raise LastLeaderError()
    except ServiceCannotRemoveSelfError:
        raise CannotRemoveSelfError()

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)
