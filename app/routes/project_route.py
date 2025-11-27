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
    ProjectMember,
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
    response_model=List[Project],
    summary="List my projects",
    description="Return all projects that the authenticated user is currently a member of.",
    responses={
        200: {
            "description": "List of projects that the current user belongs to.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": 1,
                            "name": "Waffice Backend",
                            "description": "FastAPI service for Waffice project",
                            "status": "active",
                            "start_date": "2024-03-02",
                            "end_date": None,
                            "ctime": "2024-03-02T10:00:00",
                            "mtime": "2024-05-01T12:34:56",
                            "websites": [
                                {
                                    "id": 10,
                                    "project_id": 1,
                                    "label": "GitHub",
                                    "url": "https://github.com/wafflestudio/waffice-fastapi",
                                    "kind": "repo",
                                    "is_primary": True,
                                    "ord": 1,
                                    "ctime": "2024-03-02T10:00:00",
                                    "mtime": "2024-03-02T10:00:00",
                                }
                            ],
                            "members": [
                                {
                                    "id": 100,
                                    "project_id": 1,
                                    "user_id": 23,
                                    "role": "leader",
                                    "position": "backend",
                                    "start_date": "2024-03-02",
                                    "end_date": None,
                                    "ctime": "2024-03-02T10:00:00",
                                    "mtime": "2024-03-02T10:00:00",
                                }
                            ],
                        }
                    ]
                }
            },
        }
    },
)
def project_me(
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return ProjectController.list_my_projects(db, user_id)


@router.get(
    "/project/info",
    response_model=Project,
    summary="Get project detail",
    description="Get detailed information of a project by its ID, including websites and members.",
    responses={
        200: {
            "description": "Project detail including websites and members.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "name": "Waffice Backend",
                        "description": "FastAPI service for Waffice project",
                        "status": "active",
                        "start_date": "2024-03-02",
                        "end_date": None,
                        "ctime": "2024-03-02T10:00:00",
                        "mtime": "2024-05-01T12:34:56",
                        "websites": [
                            {
                                "id": 10,
                                "project_id": 1,
                                "label": "GitHub",
                                "url": "https://github.com/wafflestudio/waffice-fastapi",
                                "kind": "repo",
                                "is_primary": True,
                                "ord": 1,
                                "ctime": "2024-03-02T10:00:00",
                                "mtime": "2024-03-02T10:00:00",
                            },
                            {
                                "id": 11,
                                "project_id": 1,
                                "label": "Service",
                                "url": "https://waffice.dev",
                                "kind": "service",
                                "is_primary": False,
                                "ord": 2,
                                "ctime": "2024-03-02T10:00:00",
                                "mtime": "2024-03-02T10:00:00",
                            },
                        ],
                        "members": [
                            {
                                "id": 100,
                                "project_id": 1,
                                "user_id": 23,
                                "role": "leader",
                                "position": "backend",
                                "start_date": "2024-03-02",
                                "end_date": None,
                                "ctime": "2024-03-02T10:00:00",
                                "mtime": "2024-03-02T10:00:00",
                            },
                            {
                                "id": 101,
                                "project_id": 1,
                                "user_id": 24,
                                "role": "member",
                                "position": "frontend",
                                "start_date": "2024-03-10",
                                "end_date": None,
                                "ctime": "2024-03-10T09:00:00",
                                "mtime": "2024-03-10T09:00:00",
                            },
                        ],
                    }
                }
            },
        },
        404: {"description": "Project not found"},
    },
)
def project_info(
    project_id: int,
    db: Session = Depends(get_db),
):
    return ProjectController.get_project_info(db, project_id)


@router.patch(
    "/project/update",
    response_model=Project,
    summary="Update project (4leader)",
    description=(
        "Update project fields and optionally replace all websites. "
        "The caller must be a leader of the target project."
    ),
    responses={
        200: {
            "description": "Updated project object.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "name": "Waffice Backend",
                        "description": "Updated description for Waffice backend",
                        "status": "active",
                        "start_date": "2024-03-02",
                        "end_date": None,
                        "ctime": "2024-03-02T10:00:00",
                        "mtime": "2024-05-10T12:00:00",
                        "websites": [
                            {
                                "id": 10,
                                "project_id": 1,
                                "label": "GitHub",
                                "url": "https://github.com/wafflestudio/waffice-fastapi",
                                "kind": "repo",
                                "is_primary": True,
                                "ord": 1,
                                "ctime": "2024-03-02T10:00:00",
                                "mtime": "2024-03-02T10:00:00",
                            }
                        ],
                        "members": [
                            {
                                "id": 100,
                                "project_id": 1,
                                "user_id": 23,
                                "role": "leader",
                                "position": "backend",
                                "start_date": "2024-03-02",
                                "end_date": None,
                                "ctime": "2024-03-02T10:00:00",
                                "mtime": "2024-03-02T10:00:00",
                            }
                        ],
                    }
                }
            },
        },
    },
)
def project_update(
    project_id: int = Body(
        ...,
        description="Target project ID",
        example=1,
    ),
    project: ProjectUpdate = Body(
        ...,
        description="Project fields to update",
        example={
            "name": "Waffice Backend",
            "description": "Updated description for Waffice backend",
            "status": "active",
            "start_date": "2024-03-02",
            "end_date": None,
        },
    ),
    websites: Optional[List[ProjectWebsiteCreate]] = Body(
        None,
        description="Optional list of websites; replaces all existing websites when provided",
        example=[
            {
                "label": "GitHub",
                "url": "https://github.com/wafflestudio/waffice-fastapi",
                "kind": "repo",
                "is_primary": True,
                "ord": 1,
            },
            {
                "label": "Service",
                "url": "https://waffice.dev",
                "kind": "service",
                "is_primary": False,
                "ord": 2,
            },
        ],
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
    response_model=ProjectMember,
    summary="Invite user to project (4leader)",
    description=(
        "Invite a user to a project. "
        "If you invite as leader, you must also be a leader. "
        "Inviting as member requires at least project membership."
    ),
    responses={
        200: {
            "description": "Created project membership.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 101,
                        "project_id": 1,
                        "user_id": 24,
                        "role": "member",
                        "position": "frontend",
                        "start_date": "2024-03-10",
                        "end_date": None,
                        "ctime": "2024-03-10T09:00:00",
                        "mtime": "2024-03-10T09:00:00",
                    }
                }
            },
        },
    },
)
def project_invite(
    project_id: int = Body(
        ...,
        description="Project ID",
        example=1,
    ),
    target_user_id: int = Body(
        ...,
        description="User to invite",
        example=24,
    ),
    role: ProjectMemberRole = Body(
        ProjectMemberRole.member,
        description="Role in project (4leader)",
        example="member",
    ),
    position: str = Body(
        ...,
        min_length=1,
        max_length=32,
        description="Position inside project (e.g. FE, BE, fullstack)",
        example="frontend",
    ),
    start_date: date = Body(
        ...,
        description="Membership start date",
        example="2024-03-10",
    ),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date",
        example=None,
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
    summary="Remove user from project (4leader)",
    description=(
        "Remove a user from a project. "
        "The caller must be a leader of the project. "
        "Leaders cannot be kicked via this endpoint."
    ),
    responses={
        200: {
            "description": "Kick result",
            "content": {
                "application/json": {
                    "example": {
                        "status": "kicked",
                        "project_id": 1,
                        "user_id": 24,
                    }
                }
            },
        },
    },
)
def project_kick(
    project_id: int = Body(
        ...,
        description="Project ID",
        example=1,
    ),
    target_user_id: int = Body(
        ...,
        description="User ID to be removed",
        example=24,
    ),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date (defaults to today on server side)",
        example=None,
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
    responses={
        200: {
            "description": "Leave result",
            "content": {
                "application/json": {
                    "example": {
                        "status": "left",
                        "project_id": 1,
                        "user_id": 23,
                    }
                }
            },
        },
    },
)
def project_leave(
    project_id: int = Body(
        ...,
        description="Project ID to leave",
        example=1,
    ),
    end_date: Optional[date] = Body(
        None,
        description="Optional membership end date (defaults to today on server side)",
        example=None,
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
    response_model=Project,
    summary="Create project",
    description=(
        "Create a new project. Caller must have executive privilege. "
        "The caller is automatically registered as the project leader."
    ),
    responses={
        200: {
            "description": "Created project object.",
            "content": {
                "application/json": {
                    "example": {
                        "id": 2,
                        "name": "New Waffice Project",
                        "description": "New internal project created by executive",
                        "status": "active",
                        "start_date": "2025-01-01",
                        "end_date": None,
                        "ctime": "2025-01-01T09:00:00",
                        "mtime": "2025-01-01T09:00:00",
                        "websites": [],
                        "members": [
                            {
                                "id": 200,
                                "project_id": 2,
                                "user_id": 23,
                                "role": "leader",
                                "position": "backend",
                                "start_date": "2025-01-01",
                                "end_date": None,
                                "ctime": "2025-01-01T09:00:00",
                                "mtime": "2025-01-01T09:00:00",
                            }
                        ],
                    }
                }
            },
        },
    },
)
def exct_project_create(
    project: ProjectCreate = Body(
        ...,
        description="Project data to create",
        example={
            "name": "New Waffice Project",
            "description": "Internal project for infra",
            "status": "active",
            "start_date": "2025-01-01",
            "end_date": None,
        },
    ),
    leader_position: str = Body(
        "backend",
        description="Position label for the creator as project leader",
        example="backend",
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

    return ProjectController.create_project_as_exec(
        db=db,
        actor=actor,
        data=project,
        leader_position=leader_position,
    )


@router.delete(
    "/exct/project/delete",
    summary="Delete project",
    description="Delete an entire project. Only users with executive privilege can perform this action.",
    responses={
        200: {
            "description": "Delete result",
            "content": {
                "application/json": {
                    "example": {
                        "status": "deleted",
                        "project_id": 2,
                    }
                }
            },
        },
    },
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
    response_model=Project,
    summary="Update project",
    description=(
        "Update project fields and optionally replace all websites. "
        "Only users with executive privilege can perform this action."
    ),
    responses={
        200: {
            "description": "Updated project object (exec).",
            "content": {
                "application/json": {
                    "example": {
                        "id": 2,
                        "name": "New Waffice Project (Updated)",
                        "description": "Updated description by exec",
                        "status": "active",
                        "start_date": "2025-01-01",
                        "end_date": None,
                        "ctime": "2025-01-01T09:00:00",
                        "mtime": "2025-02-01T09:00:00",
                        "websites": [
                            {
                                "id": 210,
                                "project_id": 2,
                                "label": "GitHub",
                                "url": "https://github.com/wafflestudio/waffice-new",
                                "kind": "repo",
                                "is_primary": True,
                                "ord": 1,
                                "ctime": "2025-02-01T09:00:00",
                                "mtime": "2025-02-01T09:00:00",
                            }
                        ],
                        "members": [
                            {
                                "id": 200,
                                "project_id": 2,
                                "user_id": 23,
                                "role": "leader",
                                "position": "backend",
                                "start_date": "2025-01-01",
                                "end_date": None,
                                "ctime": "2025-01-01T09:00:00",
                                "mtime": "2025-02-01T09:00:00",
                            }
                        ],
                    }
                }
            },
        },
    },
)
def exct_project_update(
    project_id: int = Body(
        ...,
        description="Target project ID",
        example=2,
    ),
    project: ProjectUpdate = Body(
        ...,
        description="Project fields to update",
        example={
            "name": "New Waffice Project (Updated)",
            "description": "Updated description by exec",
            "status": "active",
        },
    ),
    websites: Optional[List[ProjectWebsiteCreate]] = Body(
        None,
        description="Optional list of websites; replaces all existing websites when provided",
        example=[
            {
                "label": "GitHub",
                "url": "https://github.com/wafflestudio/waffice-new",
                "kind": "repo",
                "is_primary": True,
                "ord": 1,
            }
        ],
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
