import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import (
    get_current_user,
    require_admin,
    require_associate,
    require_regular,
)
from app.exceptions import (
    InvalidActiveRosterError,
    InvalidQualificationError,
    NotFoundError,
    RosterFileTooLargeError,
    TemporaryMemberApprovalError,
)
from app.models import AuditAction, Qualification, User
from app.schemas import (
    ActiveRosterApplyResult,
    ActiveRosterPreview,
    ActivityCreateRequest,
    ActivityDetail,
    ActivityHistoryItem,
    ActivityHistoryStatus,
    ActivityUpdateRequest,
    ApprovalRequestBody,
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
from app.services import (
    ActiveRosterService,
    ActivityService,
    AuditLogService,
    EmailService,
    ProjectService,
    UserService,
)
from app.services.active_roster import ActiveRosterDiff, ActiveRosterResolvedRow
from app.services.roster import MAX_ROSTER_FILE_BYTES, parse_member_roster

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


def _invalid_row_errors(invalid_rows: list[tuple[str, str, str]]) -> list[dict]:
    """
    Turn parse_member_roster's (name, student_id, reason) rows into blocking
    {row, field, code, message} errors. Unlike /users/temporary (which skips
    such rows and keeps going), an active-roster upload must reject the whole
    file so an admin never partially reconciles a roster.
    """
    errors = []
    for index, (name, student_id, reason) in enumerate(invalid_rows, start=1):
        field = "학번" if reason == "missing_student_id" else "이름"
        errors.append(
            {
                "row": index,
                "field": field,
                "code": reason,
                "message": _skip_message(name, student_id, reason),
            }
        )
    return errors


def _active_roster_preview(
    diff: ActiveRosterDiff, reference_date: int
) -> ActiveRosterPreview:
    return ActiveRosterPreview(
        reference_date=reference_date,
        promoted_count=len(diff.promote) + len(diff.to_create),
        demoted_count=len(diff.demote),
        maintained_count=len(diff.maintain),
        new_temporary_count=len(diff.to_create),
    )


async def _parse_and_diff_active_roster(
    file: UploadFile, db: Session
) -> tuple[list[ActiveRosterResolvedRow], ActiveRosterDiff]:
    content = await file.read(MAX_ROSTER_FILE_BYTES + 1)
    if len(content) > MAX_ROSTER_FILE_BYTES:
        raise RosterFileTooLargeError()

    valid_rows, invalid_rows = parse_member_roster(content, file.filename or "")
    if invalid_rows:
        raise InvalidActiveRosterError(_invalid_row_errors(invalid_rows))

    resolved, errors = ActiveRosterService.resolve(db, valid_rows)
    if errors:
        raise InvalidActiveRosterError(errors)

    diff = ActiveRosterService.diff(db, resolved)
    return resolved, diff


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


@router.get(
    "/me/activities",
    response_model=Response[list[ActivityHistoryItem]],
    summary="Get my activity-management history",
    description=(
        "Returns persisted activities together with pending create/update requests."
    ),
    responses={
        200: {"description": "Activities retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires REGULAR qualification or higher"},
    },
)
async def get_my_activities(
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    activities = ActivityService.list_by_user(db, current_user.id)
    activity_ids = [activity.id for activity in activities]
    pending_updates = ActivityService.pending_updates_by_activity(db, activity_ids)
    rejected_updates = ActivityService.rejected_updates_by_activity(db, activity_ids)

    items = []
    for activity in activities:
        pending_request = pending_updates.get(activity.id)
        rejected_request = rejected_updates.get(activity.id)
        if pending_request is not None:
            status = ActivityHistoryStatus.UPDATE_PENDING
            request_id = pending_request.id
        elif rejected_request is not None:
            status = ActivityHistoryStatus.REJECTED
            request_id = rejected_request.id
        else:
            status = ActivityHistoryStatus.ACTIVE
            request_id = None

        items.append(
            ActivityHistoryItem(
                id=activity.id,
                pending_request_id=request_id,
                user_id=activity.user_id,
                project_id=activity.project_id,
                project_name=activity.project_name,
                position=activity.position,
                start_date=activity.start_date,
                end_date=activity.end_date,
                status=status,
                description=activity.description,
                created_at=activity.created_at,
                updated_at=activity.updated_at,
            )
        )

    for approval_request in ActivityService.list_pending_creates(
        db, user_id=current_user.id
    ):
        body = ApprovalRequestBody.model_validate(approval_request.body)
        if body.after is None:
            continue
        items.append(
            ActivityHistoryItem(
                id=None,
                pending_request_id=approval_request.id,
                user_id=body.target_user_id,
                project_id=body.after.project_id,
                project_name=(
                    approval_request.project.name
                    if approval_request.project is not None
                    else None
                ),
                position=body.after.position,
                start_date=body.after.start_date,
                end_date=body.after.end_date,
                status=ActivityHistoryStatus.CREATE_PENDING,
                description=body.after.description,
                created_at=approval_request.created_at,
                updated_at=approval_request.updated_at,
            )
        )

    for approval_request in ActivityService.list_recent_rejected_creates(
        db, user_id=current_user.id
    ):
        body = ApprovalRequestBody.model_validate(approval_request.body)
        if body.after is None:
            continue
        items.append(
            ActivityHistoryItem(
                id=None,
                pending_request_id=approval_request.id,
                user_id=body.target_user_id,
                project_id=body.after.project_id,
                project_name=(
                    approval_request.project.name
                    if approval_request.project is not None
                    else None
                ),
                position=body.after.position,
                start_date=body.after.start_date,
                end_date=body.after.end_date,
                status=ActivityHistoryStatus.REJECTED,
                description=body.after.description,
                created_at=approval_request.created_at,
                updated_at=approval_request.updated_at,
            )
        )

    items.sort(key=lambda item: (item.start_date, item.created_at), reverse=True)
    return Response(ok=True, data=items)


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
    name: str | None = Query(None, description="Filter by name (partial match)"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    List all users with cursor-based pagination.

    **Requires**: Admin privileges.

    Returns users ordered by ID. Use `next_cursor` from the response
    to fetch subsequent pages.
    """
    users, next_cursor = UserService.list(db, cursor=cursor, limit=limit, name=name)
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
        413: {"description": "파일 용량 초과 (최대 5MB)"},
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
    content = await file.read(MAX_ROSTER_FILE_BYTES + 1)
    if len(content) > MAX_ROSTER_FILE_BYTES:
        raise RosterFileTooLargeError()
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


@router.post(
    "/active-roster/preview",
    response_model=Response[ActiveRosterPreview],
    summary="Preview an active-member roster update (.xlsx / .csv upload)",
    description=(
        "Upload the new 활동회원 명부 and see the diff against who is currently "
        "ACTIVE, without writing anything. Admin only."
    ),
    responses={
        200: {"description": "Preview computed successfully"},
        400: {
            "description": (
                "파일 양식이 올바르지 않습니다 / 이름·학번 헤더 누락 / 행 누락 데이터 / "
                "준회원·대기 회원 포함 / 학번 중복 또는 모호"
            )
        },
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        413: {"description": "파일 용량 초과 (최대 5MB)"},
        422: {"description": "명부에 회원 데이터가 없습니다"},
    },
)
async def preview_active_roster(
    file: UploadFile = File(
        ...,
        description=(
            "활동회원 명부 파일 (.xlsx 또는 .csv). 첫 행은 헤더이며 이름 열(이름/성명/name)과 "
            "학번 열(학번/student_id/sid)이 있어야 합니다."
        ),
    ),
    reference_date: int
    | None = Form(None, description="자격 변경 기준일 (Unix epoch). 생략 시 현재 시각."),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Compute (without applying) the diff between the current ACTIVE roster and
    an uploaded 활동회원 명부.

    **Requires**: Admin privileges.

    The whole file is rejected (400) if any row is missing a name/student_id,
    a student_id is duplicated in the file or ambiguous in the DB, or a
    matched member is currently ASSOCIATE or PENDING -- those must be resolved
    outside the active-roster flow first. Otherwise returns aggregate counts
    for the confirmation modal: members newly becoming ACTIVE (including new
    temporary members created for unmatched student_ids), members losing
    ACTIVE status (demoted to REGULAR), and members whose ACTIVE status is
    unchanged. Call `/users/active-roster/apply` with the same file to commit.
    """
    _resolved, diff = await _parse_and_diff_active_roster(file, db)
    return Response(
        ok=True,
        data=_active_roster_preview(diff, reference_date or int(time.time())),
    )


@router.post(
    "/active-roster/apply",
    response_model=Response[ActiveRosterApplyResult],
    summary="Apply an active-member roster update (.xlsx / .csv upload)",
    description=(
        "Upload the new 활동회원 명부 and atomically apply the diff against who "
        "is currently ACTIVE. Admin only."
    ),
    responses={
        200: {"description": "Roster applied successfully"},
        400: {
            "description": (
                "파일 양식이 올바르지 않습니다 / 이름·학번 헤더 누락 / 행 누락 데이터 / "
                "준회원·대기 회원 포함 / 학번 중복 또는 모호"
            )
        },
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        413: {"description": "파일 용량 초과 (최대 5MB)"},
        422: {"description": "명부에 회원 데이터가 없습니다"},
    },
)
async def apply_active_roster(
    file: UploadFile = File(
        ...,
        description=(
            "활동회원 명부 파일 (.xlsx 또는 .csv). 첫 행은 헤더이며 이름 열(이름/성명/name)과 "
            "학번 열(학번/student_id/sid)이 있어야 합니다."
        ),
    ),
    reference_date: int
    | None = Form(None, description="자격 변경 기준일 (Unix epoch). 생략 시 현재 시각."),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Apply the diff between the current ACTIVE roster and an uploaded
    활동회원 명부, in one transaction.

    **Requires**: Admin privileges.

    Same validation as `/users/active-roster/preview`. Unmatched student_ids
    become new temporary members (`is_temporary=True`); every qualification
    change (promotion to ACTIVE with reason "활동회원 등록", or demotion to
    REGULAR with reason "활동 기간 종료") is logged to the user's audit log,
    backdated to `reference_date` (defaults to now) so a late-entered roster
    still reflects the intended effective date.
    """
    resolved, diff = await _parse_and_diff_active_roster(file, db)
    effective_date = reference_date or int(time.time())
    result = ActiveRosterService.apply(
        db, diff, reference_date=effective_date, actor_id=admin.id
    )

    apply_result = ActiveRosterApplyResult(
        reference_date=effective_date,
        promoted_count=len(result["promoted"]),
        demoted_count=len(result["demoted"]),
        maintained_count=len(result["maintained"]),
        new_temporary_count=len(result["created_temporary"]),
        promoted=[UserBrief.model_validate(u) for u in result["promoted"]],
        demoted=[UserBrief.model_validate(u) for u in result["demoted"]],
        created_temporary=[
            UserBrief.model_validate(u) for u in result["created_temporary"]
        ],
    )
    return Response(ok=True, data=apply_result)


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
    Update a user's profile or qualification.

    **Requires**: Admin privileges.

    is_admin/is_leader/is_president are not settable here -- is_admin/
    is_president are derived from 운영팀 (admin team) project membership
    (see ProjectService.sync_admin_team_roles), and is_leader is derived
    from active project leaderships in general (see
    MemberService.sync_leader_flag) -- neither is used for authorization,
    just informational. Changes to qualification are logged in the user's
    history for audit purposes. Only provided fields will be updated.
    """
    user = UserService.get(db, user_id)
    if not user:
        raise NotFoundError("User not found")

    update_data = request.model_dump(exclude_unset=True)
    # `qualification_change_reason`은 User 모델의 컬럼이 아니라 audit log에만
    # 쓰이는 값이므로 `UserService.update`에 넘어가지 않도록 분리한다.
    qualification_change_reason = update_data.pop("qualification_change_reason", None)

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
            payload={
                "from": old_qual.value,
                "to": new_qual.value,
                "reason": qualification_change_reason,
            },
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
    background_tasks: BackgroundTasks,
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

    rejected_signup_email = (
        user.email
        if user.qualification == Qualification.PENDING and not user.is_temporary
        else None
    )
    UserService.delete(db, user)
    if rejected_signup_email:
        background_tasks.add_task(
            EmailService.send_signup_rejected, rejected_signup_email
        )
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
    background_tasks: BackgroundTasks,
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

    if user.qualification != Qualification.PENDING or not user.email:
        raise InvalidQualificationError(
            "Only pending users with a login email can be approved"
        )

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
    background_tasks.add_task(EmailService.send_signup_approved, user.email)
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
