# app/routes/project_route.py

from datetime import date
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_db
from app.controllers.project_controller import ProjectController
from app.schemas import (
    Project,
    ProjectCreate,
    ProjectMemberRole,
    ProjectUpdate,
    ProjectWebsiteCreate,
)
from app.services.user_service import UserService
from app.utils.jwt_auth import get_current_user

router = APIRouter(prefix="/api", tags=["Project"])

CurrentUserPayload = Annotated[Dict[str, Any], Depends(get_current_user)]


# ==========================================================
# PUBLIC PROJECT ROUTES
# ==========================================================


@router.get(
    "/project/me",
    summary="List my projects",
    description="Return all projects that the authenticated user is currently a member of.",
)
def project_me(
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return ProjectController.list_my_projects(db, user_id)


@router.get(
    "/project/info",
    summary="Get project detail",
    description="Get detailed information of a project by its ID, including websites and members.",
)
def project_info(
    project_id: int,
    db: Session = Depends(get_db),
):
    return ProjectController.get_project_info(db, project_id)


@router.patch(
    "/project/update",
    summary="Update project (leader only)",
    description=(
        "Update project fields and optionally replace all websites. "
        "The caller must be a leader of the target project."
    ),
)
def project_update(
    project_id: int = Body(..., description="Target project ID"),
    project: ProjectUpdate = Body(..., description="Project fields to update"),
    websites: Optional[List[ProjectWebsiteCreate]] = Body(
        None,
        description="Optional list of websites; replaces all existing websites when provided",
    ),
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return ProjectController.update_project_as_leader(
        db=db,
        project_id=project_id,
        actor_user_id=user_id,
        updates=project,
        websites=websites,
    )


@router.post(
    "/project/invite",
    summary="Invite user to project",
    description=(
        "Invite a user to a project. "
        "If you invite as leader, you must also be a leader. "
        "Inviting as member requires at least project membership."
    ),
)
def project_invite(
    project_id: int = Body(..., description="Project ID"),
    target_user_id: int = Body(..., description="User to invite"),
    role: ProjectMemberRole = Body(
        ProjectMemberRole.member,
        description="Role in project (leader or member)",
    ),
    position: str = Body(
        ...,
        min_length=1,
        max_length=32,
        description="Position inside project (e.g. FE, BE, fullstack)",
    ),
    start_date: date = Body(..., description="Membership start date"),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date",
    ),
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    actor_user_id = int(user_payload["user_id"])
    return ProjectController.invite_member(
        db=db,
        project_id=project_id,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        role=role,
        position=position,
        start_date=start_date,
        end_date=end_date,
    )


@router.post(
    "/project/kick",
    summary="Remove user from project",
    description=(
        "Remove a user from a project. "
        "The caller must be a leader of the project. "
        "Leaders cannot be kicked via this endpoint."
    ),
)
def project_kick(
    project_id: int = Body(..., description="Project ID"),
    target_user_id: int = Body(..., description="User ID to be removed"),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date (defaults to today on server side)",
    ),
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    actor_user_id = int(user_payload["user_id"])
    return ProjectController.kick_member(
        db=db,
        project_id=project_id,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        end_date=end_date,
    )


@router.post(
    "/project/leave",
    summary="Leave a project",
    description="Leave a project as the current user. The membership will be marked as ended.",
)
def project_leave(
    project_id: int = Body(..., description="Project ID to leave"),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date (defaults to today on server side)",
    ),
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return ProjectController.leave_project(
        db=db,
        project_id=project_id,
        user_id=user_id,
        end_date=end_date,
    )


# ==========================================================
# EXECUTIVE PROJECT ROUTES
# ==========================================================


@router.post(
    "/exct/project/create",
    summary="Create project (exec only)",
    description=(
        "Create a new project. Caller must have executive privilege. "
        "The caller is automatically registered as the project leader."
    ),
)
def exct_project_create(
    project: ProjectCreate,
    leader_position: str = "etc",
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    actor = UserService.get_with_links(db, user_id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Actor user not found",
        )

    return ProjectController.create_project_as_exec(
        db=db,
        actor=actor,
        data=project,
        leader_position=leader_position,
    )


@router.delete(
    "/exct/project/delete",
    summary="Delete project (exec only)",
    description="Delete an entire project. Only users with executive privilege can perform this action.",
)
def exct_project_delete(
    project_id: int,
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    actor = UserService.get_with_links(db, user_id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Actor user not found",
        )

    return ProjectController.delete_project_as_exec(
        db=db,
        actor=actor,
        project_id=project_id,
    )


@router.patch(
    "/exct/project/update",
    summary="Update project (exec only)",
    description=(
        "Update project fields and optionally replace all websites. "
        "Only users with executive privilege can perform this action."
    ),
)
def exct_project_update(
    project_id: int = Body(..., description="Target project ID"),
    project: ProjectUpdate = Body(..., description="Project fields to update"),
    websites: Optional[List[ProjectWebsiteCreate]] = Body(
        None,
        description="Optional list of websites; replaces all existing websites when provided",
    ),
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    actor = UserService.get_with_links(db, user_id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Actor user not found",
        )

    return ProjectController.update_project_as_exec(
        db=db,
        actor=actor,
        project_id=project_id,
        updates=project,
        websites=websites,
    )
