from fastapi import APIRouter, Depends, HTTPException, Query, status
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
@router.get("/me", response_model=Response[UserDetail])
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Get my own profile"""
    return Response(ok=True, data=current_user)


@router.patch("/me", response_model=Response[UserDetail])
async def update_my_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(require_associate),
    db: Session = Depends(get_db),
):
    """Update my own profile (requires associate or higher)"""
    updated_user = UserService.update(
        db, current_user, **request.model_dump(exclude_unset=True)
    )
    return Response(ok=True, data=updated_user)


@router.get("/me/history", response_model=Response[list[HistoryDetail]])
async def get_my_history(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get my history"""
    histories = HistoryService.list_by_user(db, current_user.id)
    return Response(ok=True, data=histories)


@router.get("/me/projects", response_model=Response[list[ProjectBrief]])
async def get_my_projects(
    current_user: User = Depends(require_regular), db: Session = Depends(get_db)
):
    """Get my projects (requires regular or higher)"""
    projects = ProjectService.list_by_user(db, current_user.id)
    return Response(ok=True, data=projects)


# === Admin management ===
@router.get("", response_model=Response[CursorPage[UserDetail]])
async def list_users(
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users with cursor pagination (admin only)"""
    users, next_cursor = UserService.list(db, cursor=cursor, limit=limit)
    return Response(ok=True, data=CursorPage(items=users, next_cursor=next_cursor))


@router.get("/pending", response_model=Response[list[UserDetail]])
async def list_pending_users(
    _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """List all pending users (admin only)"""
    users = UserService.list_pending(db)
    return Response(ok=True, data=users)


@router.get("/{user_id}", response_model=Response[UserDetail])
async def get_user(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get user detail (admin only)"""
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")
    return Response(ok=True, data=user)


@router.patch("/{user_id}", response_model=Response[UserDetail])
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update user (admin only)"""
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


@router.delete("/{user_id}", response_model=Response[None])
async def delete_user(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete user (soft delete, admin only)"""
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    UserService.delete(db, user)
    return Response(ok=True, message="User deleted successfully")


@router.post("/{user_id}/approve", response_model=Response[UserDetail])
async def approve_user(
    user_id: int,
    request: ApproveRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve pending user and change qualification (admin only)"""
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


@router.get("/{user_id}/history", response_model=Response[list[HistoryDetail]])
async def get_user_history(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get user history (admin only)"""
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    histories = HistoryService.list_by_user(db, user_id)
    return Response(ok=True, data=histories)
