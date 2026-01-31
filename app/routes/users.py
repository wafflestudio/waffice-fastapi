from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import (
    get_current_user,
    require_admin,
    require_associate,
    require_regular,
)
from app.exceptions import InvalidQualificationError, NotFoundError
from app.models import HistoryAction, Qualification, User
from app.schemas import (
    ApproveRequest,
    CursorPage,
    HistoryDetail,
    ProfileUpdateRequest,
    ProjectBrief,
    Response,
    UserDetail,
    UserUpdateRequest,
)
from app.services import HistoryService, ProjectService, UserService

router = APIRouter()


# === Own profile ===
@router.get(
    "/me",
    response_model=Response[UserDetail],
    summary="Get my profile",
    description="Returns the current authenticated user's complete profile.",
    responses={
        200: {"description": "User profile retrieved successfully"},
        401: {"description": "Not authenticated"},
    },
)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """
    Get the current user's own profile.

    Available to any authenticated user regardless of qualification level.
    Returns complete profile information including contact details and links.
    """
    return Response(ok=True, data=current_user)


@router.patch(
    "/me",
    response_model=Response[UserDetail],
    summary="Update my profile",
    description="Update the current user's profile information.",
    responses={
        200: {"description": "Profile updated successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Pending users cannot update profile"},
    },
)
async def update_my_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(require_associate),
    db: Session = Depends(get_db),
):
    """
    Update the current user's profile.

    **Requires**: ASSOCIATE qualification or higher.

    Pending users cannot update their profile until approved by an admin.
    Only provided fields will be updated; omitted fields remain unchanged.
    """
    updated_user = UserService.update(
        db, current_user, **request.model_dump(exclude_unset=True)
    )
    return Response(ok=True, data=updated_user)


@router.get(
    "/me/history",
    response_model=Response[list[HistoryDetail]],
    summary="Get my activity history",
    description="Returns the current user's audit log entries.",
    responses={
        200: {"description": "History retrieved successfully"},
        401: {"description": "Not authenticated"},
    },
)
async def get_my_history(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get the current user's activity history.

    Returns audit log entries including qualification changes, admin status
    changes, and project membership events. Sorted by most recent first.
    """
    histories = HistoryService.list_by_user(db, current_user.id)
    return Response(ok=True, data=histories)


@router.get(
    "/me/projects",
    response_model=Response[list[ProjectBrief]],
    summary="Get my projects",
    description="Returns projects where the current user is a member.",
    responses={
        200: {"description": "Projects retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires REGULAR qualification or higher"},
    },
)
async def get_my_projects(
    current_user: User = Depends(require_regular), db: Session = Depends(get_db)
):
    """
    Get projects where the current user is an active member.

    **Requires**: REGULAR qualification or higher.

    Returns a list of projects (active membership only, excludes projects
    the user has left). Use `/projects/{id}` for full project details.
    """
    projects = ProjectService.list_by_user(db, current_user.id)
    return Response(ok=True, data=projects)


# === Admin management ===
@router.get(
    "",
    response_model=Response[CursorPage[UserDetail]],
    summary="List all users",
    description="Returns paginated list of all users. Admin only.",
    responses={
        200: {"description": "Users retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
    },
)
async def list_users(
    cursor: int | None = Query(
        None, description="Pagination cursor (user ID). Omit for first page."
    ),
    limit: int = Query(
        20, ge=1, le=100, description="Number of users per page (1-100)"
    ),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    List all users with cursor-based pagination.

    **Requires**: Admin privileges.

    Returns users ordered by ID. Use `next_cursor` from the response
    to fetch subsequent pages.
    """
    users, next_cursor = UserService.list(db, cursor=cursor, limit=limit)
    return Response(ok=True, data=CursorPage(items=users, next_cursor=next_cursor))


@router.get(
    "/pending",
    response_model=Response[list[UserDetail]],
    summary="List pending users",
    description="Returns all users awaiting approval. Admin only.",
    responses={
        200: {"description": "Pending users retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
    },
)
async def list_pending_users(
    _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """
    List all users with PENDING qualification awaiting admin approval.

    **Requires**: Admin privileges.

    Use `/users/{id}/approve` to approve a pending user.
    """
    users = UserService.list_pending(db)
    return Response(ok=True, data=users)


@router.get(
    "/{user_id}",
    response_model=Response[UserDetail],
    summary="Get user by ID",
    description="Returns detailed information for a specific user. Admin only.",
    responses={
        200: {"description": "User retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Get a specific user's complete profile.

    **Requires**: Admin privileges.

    Returns full user details including qualification, admin status,
    and all profile fields.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")
    return Response(ok=True, data=user)


@router.patch(
    "/{user_id}",
    response_model=Response[UserDetail],
    summary="Update user",
    description="Update any user's profile and status. Admin only.",
    responses={
        200: {"description": "User updated successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Update a user's profile, qualification, or admin status.

    **Requires**: Admin privileges.

    Changes to qualification and admin status are logged in the user's
    history for audit purposes. Only provided fields will be updated.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    update_data = request.model_dump(exclude_unset=True)

    # Log qualification change
    if (
        "qualification" in update_data
        and update_data["qualification"] != user.qualification
    ):
        old_qual = user.qualification
        new_qual = update_data["qualification"]
        HistoryService.log(
            db=db,
            user_id=user.id,
            action=HistoryAction.QUALIFICATION_CHANGED,
            payload={"from": old_qual.value, "to": new_qual.value},
            actor_id=admin.id,
        )

    # Log admin changes
    if "is_admin" in update_data and update_data["is_admin"] != user.is_admin:
        if update_data["is_admin"]:
            HistoryService.log(
                db=db,
                user_id=user.id,
                action=HistoryAction.ADMIN_GRANTED,
                payload={},
                actor_id=admin.id,
            )
        else:
            HistoryService.log(
                db=db,
                user_id=user.id,
                action=HistoryAction.ADMIN_REVOKED,
                payload={},
                actor_id=admin.id,
            )

    updated_user = UserService.update(db, user, **update_data)
    return Response(ok=True, data=updated_user)


@router.delete(
    "/{user_id}",
    response_model=Response[None],
    summary="Delete user",
    description="Soft-delete a user. Admin only.",
    responses={
        200: {"description": "User deleted successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def delete_user(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Soft-delete a user.

    **Requires**: Admin privileges.

    The user record is marked as deleted but retained in the database.
    Deleted users cannot log in and won't appear in user lists.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    UserService.delete(db, user)
    return Response(ok=True, message="User deleted successfully")


@router.post(
    "/{user_id}/approve",
    response_model=Response[UserDetail],
    summary="Approve pending user",
    description="Approve a pending user and set their qualification level. Admin only.",
    responses={
        200: {"description": "User approved successfully"},
        400: {"description": "Cannot approve to PENDING status"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def approve_user(
    user_id: int,
    request: ApproveRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Approve a pending user and set their qualification level.

    **Requires**: Admin privileges.

    This is the primary way to activate new users. The qualification
    determines the user's access level:
    - **ASSOCIATE**: Basic member with limited access
    - **REGULAR**: Standard member who can view projects
    - **ACTIVE**: Fully active member with all privileges

    Cannot set qualification to PENDING (use this endpoint only for approval).
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    # Cannot approve to pending
    if request.qualification == Qualification.PENDING:
        raise InvalidQualificationError("Cannot approve user to pending status")

    old_qual = user.qualification
    user = UserService.update(db, user, qualification=request.qualification)

    # Log qualification change
    HistoryService.log(
        db=db,
        user_id=user.id,
        action=HistoryAction.QUALIFICATION_CHANGED,
        payload={"from": old_qual.value, "to": request.qualification.value},
        actor_id=admin.id,
    )

    return Response(ok=True, data=user)


@router.get(
    "/{user_id}/history",
    response_model=Response[list[HistoryDetail]],
    summary="Get user's activity history",
    description="Returns a user's audit log entries. Admin only.",
    responses={
        200: {"description": "History retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user_history(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Get a user's complete activity history.

    **Requires**: Admin privileges.

    Returns all audit log entries for the user including qualification
    changes, admin status changes, and project membership events.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    histories = HistoryService.list_by_user(db, user_id)
    return Response(ok=True, data=histories)
