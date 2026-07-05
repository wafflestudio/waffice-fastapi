from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import (
    get_current_user,
    require_admin,
    require_associate,
    require_regular,
)
from app.exceptions import (
    InvalidQualificationError,
    NotFoundError,
    TemporaryMemberApprovalError,
)
from app.models import AuditAction, Qualification, User, UserRole
from app.schemas import (
    ActivityCreateRequest,
    ActivityDetail,
    ActivityUpdateRequest,
    ApproveRequest,
    AuditLogDetail,
    CursorPage,
    ProfileUpdateRequest,
    ProjectBrief,
    Response,
    SkippedMember,
    TempMemberImportResult,
    UserBrief,
    UserDetail,
    UserUpdateRequest,
)
from app.services import ActivityService, AuditLogService, ProjectService, UserService
from app.services.roster import parse_member_roster

router = APIRouter()


def _skip_message(name: str, student_id: str, reason: str) -> str:
    """Human-readable Korean explanation for a skipped roster row."""
    if reason == "missing_student_id":
        return f'"{name}"의 학번을 찾을 수 없습니다.'
    if reason == "missing_name":
        return f'"{student_id}"의 이름을 찾을 수 없습니다.'
    if reason == "already_exists":
        return f'"{student_id}"은(는) 이미 등록된 학번입니다.'
    if reason == "duplicate_in_request":
        return f'"{student_id}"이(가) 파일에 중복되어 있습니다.'
    return f'"{name or student_id}"의 데이터 형식이 올바르지 않습니다.'


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
    "/me/audit-log",
    response_model=Response[list[AuditLogDetail]],
    summary="Get my audit log",
    description="Returns the current user's audit log entries.",
    responses={
        200: {"description": "Audit log retrieved successfully"},
        401: {"description": "Not authenticated"},
    },
)
async def get_my_audit_log(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get the current user's activity history.

    Returns audit log entries including qualification changes, admin status
    changes, and project membership events. Sorted by most recent first.
    """
    histories = AuditLogService.list_by_user(db, current_user.id)
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
    cursor: int
    | None = Query(
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


@router.post(
    "/temporary",
    response_model=Response[TempMemberImportResult],
    summary="Import temporary members from a roster (.xlsx / .csv upload)",
    description=(
        "Upload a member roster (.xlsx or .csv) to bulk-create temporary members. "
        "Admin only."
    ),
    responses={
        200: {"description": "Roster imported successfully"},
        400: {"description": "파일 양식이 올바르지 않습니다 / 이름·학번 헤더 누락 / 최대 행 초과"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        422: {"description": "명부에 회원 데이터가 없습니다"},
    },
)
async def import_temporary_members(
    file: UploadFile = File(
        ...,
        description=(
            "명부 파일 (.xlsx 또는 .csv). 첫 행은 헤더이며 이름 열(이름/성명/name)과 "
            "학번 열(학번/student_id/sid)이 있어야 합니다."
        ),
    ),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Import a member roster (.xlsx or .csv) as temporary members.

    **Requires**: Admin privileges.

    The uploaded file is parsed on the backend. The first row is the header, and
    the name / student_id columns are located by header text (case-insensitive;
    Korean or English; column order does not matter):
    - name:       이름 / 성명 / name
    - student_id: 학번 / student_id / sid

    Each data row becomes a temporary `User` with only `name` and `student_id`
    populated (no email/OAuth identity, `is_temporary=True`, `qualification=PENDING`).

    A row is skipped (reported in `skipped` with a `reason` and a Korean `message`)
    when a member with that student_id already exists (`already_exists`), the same
    student_id appears more than once in the file (`duplicate_in_request`), the row
    is missing its student_id (`missing_student_id`) or name (`missing_name`), or the
    value is malformed (`invalid`). A whole-file error (400/422) is raised only for a
    bad file, a missing header column, or an empty roster.

    Idempotency caveats (matching is application-level, not DB-enforced):
    - Re-uploading the same roster is safe (existing rows skip as `already_exists`).
    - `student_id` has no UNIQUE constraint, so two *concurrent* uploads of the
      same student_id could both create a row. Avoid simultaneous uploads.
    - Existing members who never recorded a `student_id` cannot be matched and
      will be duplicated as temporary members.
    """
    content = await file.read()
    valid_rows, invalid_rows = parse_member_roster(content, file.filename)

    created, skipped = UserService.bulk_create_temporary(db, valid_rows)
    skipped = invalid_rows + skipped

    result = TempMemberImportResult(
        created_count=len(created),
        skipped_count=len(skipped),
        created=[UserBrief.model_validate(u) for u in created],
        skipped=[
            SkippedMember(
                name=name,
                student_id=student_id,
                reason=reason,
                message=_skip_message(name, student_id, reason),
            )
            for name, student_id, reason in skipped
        ],
    )
    return Response(ok=True, data=result)


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
        AuditLogService.log(
            db=db,
            user_id=user.id,
            action=AuditAction.QUALIFICATION_CHANGED,
            payload={"from": old_qual.value, "to": new_qual.value},
            actor_id=admin.id,
        )

    # Log role changes
    if "role" in update_data and update_data["role"] != user.role:
        AuditLogService.log(
            db=db,
            user_id=user.id,
            action=AuditAction.ROLE_CHANGED,
            payload={"from": user.role.value, "to": update_data["role"].value},
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
        400: {
            "description": "Cannot approve to PENDING status, or target is a temporary member"
        },
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

    # Temporary members are roster placeholders with no OAuth identity; they are
    # excluded from the pending-approval queue and must not be approved directly.
    if user.is_temporary:
        raise TemporaryMemberApprovalError()

    # Cannot approve to pending
    if request.qualification == Qualification.PENDING:
        raise InvalidQualificationError("Cannot approve user to pending status")

    old_qual = user.qualification

    AuditLogService.log(
        db=db,
        user_id=user.id,
        action=AuditAction.QUALIFICATION_CHANGED,
        payload={"from": old_qual.value, "to": request.qualification.value},
        actor_id=admin.id,
    )

    user = UserService.update(db, user, qualification=request.qualification)
    return Response(ok=True, data=user)


@router.get(
    "/{user_id}/audit-log",
    response_model=Response[list[AuditLogDetail]],
    summary="Get user's audit log",
    description="Returns a user's audit log entries. Admin only.",
    responses={
        200: {"description": "Audit log retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user_audit_log(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Get a user's complete audit log.

    **Requires**: Admin privileges.

    Returns all audit log entries for the user including qualification
    changes, admin status changes, and project membership events.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    histories = AuditLogService.list_by_user(db, user_id)
    return Response(ok=True, data=histories)


# === User activities ===
@router.get(
    "/{user_id}/activities",
    response_model=Response[list[ActivityDetail]],
    summary="List user's activities",
    description="Returns all activity records for a user. Admin only.",
    responses={
        200: {"description": "Activities retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def list_user_activities(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    activities = ActivityService.list_by_user(db, user_id)
    return Response(ok=True, data=activities)


@router.post(
    "/{user_id}/activities",
    response_model=Response[ActivityDetail],
    summary="Add user activity",
    description="Add an activity record to a user. Admin only.",
    responses={
        200: {"description": "Activity created successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def create_user_activity(
    user_id: int,
    request: ActivityCreateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    if not ProjectService.get(db, request.project_id):
        raise NotFoundError("Project not found")

    activity = ActivityService.create(db, user_id, **request.model_dump())
    return Response(ok=True, data=activity)


@router.patch(
    "/{user_id}/activities/{activity_id}",
    response_model=Response[ActivityDetail],
    summary="Update user activity",
    description="Update an activity record. Admin only.",
    responses={
        200: {"description": "Activity updated successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User or activity not found"},
    },
)
async def update_user_activity(
    user_id: int,
    activity_id: int,
    request: ActivityUpdateRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    activity = ActivityService.get(db, activity_id)
    if not activity or activity.user_id != user_id:
        raise NotFoundError("Activity not found")

    update_data = request.model_dump(exclude_unset=True)
    if "project_id" in update_data and not ProjectService.get(
        db, update_data["project_id"]
    ):
        raise NotFoundError("Project not found")

    updated = ActivityService.update(db, activity, **update_data)
    return Response(ok=True, data=updated)


@router.delete(
    "/{user_id}/activities/{activity_id}",
    response_model=Response[None],
    summary="Delete user activity",
    description="Delete an activity record. Admin only.",
    responses={
        200: {"description": "Activity deleted successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User or activity not found"},
    },
)
async def delete_user_activity(
    user_id: int,
    activity_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    activity = ActivityService.get(db, activity_id)
    if not activity or activity.user_id != user_id:
        raise NotFoundError("Activity not found")

    ActivityService.delete(db, activity)
    return Response(ok=True, message="Activity deleted successfully")
