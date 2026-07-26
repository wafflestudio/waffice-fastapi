import io

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_admin, require_regular
from app.deps.project import require_leader_or_admin
from app.exceptions import (
    CannotRemoveSelfError,
    InvalidProjectMemberFileError,
    LastLeaderError,
    NoLeaderError,
    NotFoundError,
    RosterFileTooLargeError,
)
from app.models import ActivityStatus, MemberRole, User
from app.schemas import (
    CursorPage,
    MemberDetail,
    MemberInput,
    MemberUpdateRequest,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectListItem,
    ProjectPageDetail,
    ProjectUpdateRequest,
    Response,
)
from app.services import MemberService, ProjectService, UserService
from app.services.member import (
    CannotRemoveSelfError as ServiceCannotRemoveSelfError,
    LastLeaderError as ServiceLastLeaderError,
)
from app.services.roster import (
    MAX_ROSTER_FILE_BYTES,
    XLSX_CONTENT_TYPE,
    build_multi_project_member_template,
    build_project_member_template,
    parse_multi_project_member_roster,
    parse_project_member_roster,
)

router = APIRouter()


@router.get(
    "",
    response_model=Response[CursorPage[ProjectListItem]],
    summary="List all projects",
    description="Returns paginated list of all projects.",
    responses={
        200: {"description": "Projects retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires REGULAR qualification or higher"},
    },
)
async def list_projects(
    cursor: int
    | None = Query(
        None, description="Pagination cursor (project ID). Omit for first page."
    ),
    limit: int = Query(
        20, ge=1, le=100, description="Number of projects per page (1-100)"
    ),
    _user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    List all projects with cursor-based pagination.

    **Requires**: REGULAR qualification or higher.

    Returns project summaries ordered by ID. Use `next_cursor` from the
    response to fetch subsequent pages. For full project details including
    members, use `GET /projects/{id}`.
    """
    projects, next_cursor = ProjectService.list(db, cursor=cursor, limit=limit)
    items = []
    for project in projects:
        active_members = sorted(
            (
                member
                for member in project.members
                if member.left_at is None
                and member.user is not None
                and member.user.deleted_at is None
            ),
            key=lambda member: (member.user.name, member.user_id),
        )
        items.append(
            ProjectListItem(
                id=project.id,
                name=project.name,
                leader_names=[
                    member.user.name
                    for member in active_members
                    if member.role == MemberRole.LEADER
                ],
                member_count=len(active_members),
                active_member_names=[member.user.name for member in active_members],
                status=project.status,
            )
        )
    return Response(ok=True, data=CursorPage(items=items, next_cursor=next_cursor))


@router.get(
    "/{project_id}/members/template",
    summary="Download the project member XLSX template",
    responses={
        200: {"content": {XLSX_CONTENT_TYPE: {}}},
        401: {"description": "Not authenticated"},
        403: {"description": "Must be project leader or admin"},
        404: {"description": "Project not found"},
    },
)
async def download_project_member_template(
    project_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    require_leader_or_admin(project_id, current_user, db)
    members = [
        member
        for member in MemberService.list_active(db, project_id)
        if member.user is not None and member.user.deleted_at is None
    ]
    content = build_project_member_template(members)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=XLSX_CONTENT_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="project-{project_id}-members.xlsx"'
            )
        },
    )


@router.put(
    "/{project_id}/members/bulk",
    response_model=Response[ProjectDetail],
    summary="Replace all active project members from an XLSX or CSV file. Admin only.",
    responses={
        200: {"description": "Project members replaced successfully"},
        400: {"description": "Invalid workbook or resulting member roster"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "Project or user not found"},
        413: {"description": "File exceeds 5MB"},
    },
)
async def replace_project_members(
    project_id: int,
    file: UploadFile = File(..., description="팀원 명단 .xlsx 또는 .csv 파일"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    require_leader_or_admin(project_id, admin, db)

    content = await file.read(MAX_ROSTER_FILE_BYTES + 1)
    if len(content) > MAX_ROSTER_FILE_BYTES:
        raise RosterFileTooLargeError()

    rows, errors = parse_project_member_roster(content, file.filename or "")
    if errors:
        raise InvalidProjectMemberFileError(errors)

    project = ProjectService.replace_members(
        db, project_id=project_id, rows=rows, actor_id=admin.id
    )
    return Response(ok=True, data=project)


@router.get(
    "/members/bulk-all-projects/template",
    summary="Download the multi-project member XLSX template",
    responses={
        200: {"content": {XLSX_CONTENT_TYPE: {}}},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
    },
)
async def download_multi_project_member_template(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    members = [
        member
        for member in MemberService.list_all_active(db)
        if member.user is not None and member.user.deleted_at is None
    ]
    content = build_multi_project_member_template(members)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": 'attachment; filename="project-members.xlsx"'},
    )


@router.put(
    "/members/bulk-all-projects",
    response_model=Response[list[ProjectDetail]],
    summary="Replace member rosters across multiple projects from one XLSX file, routed by project name. Admin only.",
    responses={
        200: {"description": "Project member rosters replaced successfully"},
        400: {"description": "Invalid workbook or resulting member roster"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        413: {"description": "File exceeds 5MB"},
    },
)
async def replace_project_members_by_name(
    file: UploadFile = File(..., description="프로젝트명 포함 팀원 명단 .xlsx 파일"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    content = await file.read(MAX_ROSTER_FILE_BYTES + 1)
    if len(content) > MAX_ROSTER_FILE_BYTES:
        raise RosterFileTooLargeError()

    rows, errors = parse_multi_project_member_roster(content, file.filename or "")
    if errors:
        raise InvalidProjectMemberFileError(errors)

    projects = ProjectService.replace_members_by_project_name(
        db, rows=rows, actor_id=admin.id
    )
    return Response(ok=True, data=projects)


@router.post(
    "",
    response_model=Response[ProjectDetail],
    summary="Create a new project",
    description="Create a new project with initial members. Admin only.",
    responses={
        200: {"description": "Project created successfully"},
        400: {"description": "Validation error (e.g., no leader specified)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "One or more member user IDs not found"},
    },
)
async def create_project(
    request: ProjectCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Create a new project with initial members.

    **Requires**: Admin privileges.

    The `members` list must include at least one user with the `leader` role.
    All specified user IDs must exist in the system.

    **Project statuses:**
    - `active`: Ongoing development (default)
    - `maintenance`: Stable, minimal updates
    - `ended`: Completed or discontinued
    """
    # Validate: at least one leader is required
    has_leader = any(m.role == MemberRole.LEADER for m in request.members)
    if not has_leader:
        raise NoLeaderError()

    # Validate all members exist before creating anything
    for member_input in request.members:
        user = UserService.get(db, member_input.user_id)
        if not user:
            raise NotFoundError(f"User {member_input.user_id} not found")

    # Create project
    project_data = request.model_dump(exclude={"members"})
    project = ProjectService.create(db, **project_data)

    # Add members (all validated above)
    for member_input in request.members:
        MemberService.add(
            db=db,
            project_id=project.id,
            user_id=member_input.user_id,
            role=member_input.role,
            position=member_input.position,
            actor_id=admin.id,
        )

    # Commit the entire transaction (project + all members)
    db.commit()

    # Reload project with members
    project = ProjectService.get_with_members(db, project.id)
    return Response(ok=True, data=project)


@router.get(
    "/{project_id}",
    response_model=Response[ProjectPageDetail],
    summary="Get project details",
    description="Returns project information. Members are available separately.",
    responses={
        200: {"description": "Project retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires REGULAR qualification or higher"},
        404: {"description": "Project not found"},
    },
)
async def get_project(
    project_id: int,
    _user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Get complete project details.

    **Requires**: REGULAR qualification or higher.

    Use `GET /projects/{id}/members` for paginated membership records.
    """
    project = ProjectService.get(db, project_id)
    if not project:
        raise NotFoundError("Project not found")
    return Response(ok=True, data=project)


@router.patch(
    "/{project_id}",
    response_model=Response[ProjectDetail],
    summary="Update project",
    description="Update project details. Requires leader or admin.",
    responses={
        200: {"description": "Project updated successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Must be project leader or admin"},
        404: {"description": "Project not found"},
    },
)
async def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Update project details.

    **Requires**: Project leader or admin privileges.

    Only provided fields will be updated; omitted fields remain unchanged.
    Use this to update project name, description, status, dates, or links.
    """
    # Check permission
    project = require_leader_or_admin(project_id, user, db)

    # Update project
    update_data = request.model_dump(exclude_unset=True)
    project = ProjectService.update(db, project, **update_data)

    # Reload with members
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.delete(
    "/{project_id}",
    response_model=Response[None],
    summary="Delete project",
    description="Soft-delete a project. Admin only.",
    responses={
        200: {"description": "Project deleted successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "Project not found"},
    },
)
async def delete_project(
    project_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Soft-delete a project.

    **Requires**: Admin privileges.

    The project record is marked as deleted but retained in the database.
    Deleted projects won't appear in project lists.
    """
    project = ProjectService.get(db, project_id)
    if not project:
        raise NotFoundError("Project not found")

    ProjectService.delete(db, project)
    return Response(ok=True, message="Project deleted successfully")


# === Project Members ===
@router.get(
    "/{project_id}/members",
    response_model=Response[CursorPage[MemberDetail]],
    summary="List project members",
    description="Returns paginated current and former project memberships.",
    responses={
        200: {"description": "Members retrieved successfully"},
        401: {"description": "Not authenticated"},
        403: {"description": "Requires REGULAR qualification or higher"},
        404: {"description": "Project not found"},
    },
)
async def list_project_members(
    project_id: int,
    status: ActivityStatus
    | None = Query(
        None,
        description="Filter by activity status; omit to return all",
    ),
    cursor: int | None = Query(None, description="Membership ID pagination cursor"),
    limit: int = Query(20, ge=1, le=100),
    keyword: str
    | None = Query(
        None,
        description="Partial match on name, position, email, or GitHub username",
    ),
    _user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    if not ProjectService.get(db, project_id):
        raise NotFoundError("Project not found")
    members, next_cursor = MemberService.list(
        db,
        project_id,
        cursor=cursor,
        limit=limit,
        status=status,
        keyword=keyword,
    )
    return Response(ok=True, data=CursorPage(items=members, next_cursor=next_cursor))


@router.post(
    "/{project_id}/members",
    response_model=Response[ProjectDetail],
    summary="Add project member",
    description="Add a user to the project. Requires leader or admin.",
    responses={
        200: {"description": "Member added successfully (or already exists)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Must be project leader or admin"},
        404: {"description": "Project or user not found"},
    },
)
async def add_project_member(
    project_id: int,
    member_input: MemberInput,
    user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Add a new member to the project.

    **Requires**: Project leader or admin privileges.

    This operation is idempotent: if the user is already an active member,
    their existing membership is returned without changes.

    **Roles:**
    - `leader`: Can manage project and its members
    - `member`: Regular project participant
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
    db.commit()

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=Response[ProjectDetail],
    summary="Update project member",
    description="Update a member's role or position. Requires leader or admin.",
    responses={
        200: {"description": "Member updated successfully"},
        400: {"description": "Cannot demote the last leader"},
        401: {"description": "Not authenticated"},
        403: {"description": "Must be project leader or admin"},
        404: {"description": "Project or member not found"},
    },
)
async def update_project_member(
    project_id: int,
    user_id: int,
    request: MemberUpdateRequest,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Update a project member's role or position.

    **Requires**: Project leader or admin privileges.

    **Constraints:**
    - Cannot demote the last remaining leader (project must always have at least one leader)
    - Only provided fields will be updated

    **Roles:**
    - `leader`: Can manage project and its members
    - `member`: Regular project participant
    """
    # Check permission
    require_leader_or_admin(project_id, current_user, db)

    # Get member
    member = MemberService.get_active(db, project_id, user_id)
    if not member:
        raise NotFoundError("Member not found in this project")

    # Update member
    changes = request.model_dump(exclude_unset=True)
    try:
        if changes:
            MemberService.change(
                db=db,
                member=member,
                actor_id=current_user.id,
                **changes,
            )
    except ServiceLastLeaderError:
        raise LastLeaderError()
    db.commit()

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)


@router.delete(
    "/{project_id}/members/{user_id}",
    response_model=Response[ProjectDetail],
    summary="Remove project member",
    description="Remove a member from the project. Requires leader or admin.",
    responses={
        200: {"description": "Member removed successfully"},
        400: {
            "description": "Cannot remove the last leader, or cannot remove yourself"
        },
        401: {"description": "Not authenticated"},
        403: {"description": "Must be project leader or admin"},
        404: {"description": "Project or member not found"},
    },
)
async def remove_project_member(
    project_id: int,
    user_id: int,
    current_user: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    """
    Remove a member from the project.

    **Requires**: Project leader or admin privileges.

    **Constraints:**
    - Cannot remove the last remaining leader (promote another member first)
    - Leaders cannot remove themselves (must be demoted or removed by another leader/admin)

    The member record is soft-deleted (marked with `left_at` date) for
    historical reference.
    """
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
    db.commit()

    # Return updated project
    project = ProjectService.get_with_members(db, project_id)
    return Response(ok=True, data=project)
