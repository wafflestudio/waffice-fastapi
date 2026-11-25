from fastapi import APIRouter, Depends, Query, Response as FastAPIResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_regular
from app.models import User
from app.schemas import (
    ActivityHistoryAdminItem,
    ActivityHistoryStatus,
    Page,
    Response,
    UserBrief,
)
from app.services import ActivityService

router = APIRouter()


@router.get(
    "",
    response_model=Response[Page[ActivityHistoryAdminItem]],
    summary="List visible users' activities",
    description=(
        "Returns persisted activities with offset-based pagination for members with "
        "REGULAR qualification or higher. Only admins can view records of "
        "soft-deleted users or signup applicants awaiting approval."
    ),
    responses={
        403: {"description": "Requires REGULAR qualification or higher"},
    },
)
async def list_activities(
    response: FastAPIResponse,
    page: int = Query(default=1, ge=1, description="Page number (1-based)."),
    size: int = Query(
        default=10, ge=1, le=100, description="Number of items per page."
    ),
    viewer: User = Depends(require_regular),
    db: Session = Depends(get_db),
):
    activities, total = ActivityService.list_all_paged(
        db, page=page, size=size, exclude_hidden_users=not viewer.has_admin_access
    )
    pending_updates = ActivityService.pending_updates_by_activity(
        db, [activity.id for activity in activities]
    )

    items = [
        ActivityHistoryAdminItem(
            id=activity.id,
            pending_request_id=(
                pending_updates[activity.id].id
                if activity.id in pending_updates
                else None
            ),
            user_id=activity.user_id,
            user=UserBrief.model_validate(activity.user),
            project_id=activity.project_id,
            project_name=activity.project_name,
            position=activity.position,
            start_date=activity.start_date,
            end_date=activity.end_date,
            status=(
                ActivityHistoryStatus.UPDATE_PENDING
                if activity.id in pending_updates
                else ActivityHistoryStatus.ACTIVE
            ),
            description=activity.description,
            created_at=activity.created_at,
            updated_at=activity.updated_at,
        )
        for activity in activities
    ]
    response.headers["Cache-Control"] = "private, no-store"
    return Response(
        ok=True,
        data=Page(items=items, total=total, page=page, size=size),
    )
