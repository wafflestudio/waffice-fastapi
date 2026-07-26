from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_admin
from app.models import User
from app.schemas import (
    ActivityHistoryAdminItem,
    ActivityHistoryStatus,
    CursorPage,
    Response,
    UserBrief,
)
from app.services import ActivityService

router = APIRouter()


@router.get(
    "",
    response_model=Response[CursorPage[ActivityHistoryAdminItem]],
    summary="List all users' activities",
    description=(
        "Returns persisted activities for all users using an ID-based cursor. "
        "Admin only."
    ),
)
async def list_activities(
    cursor: int
    | None = Query(
        default=None,
        ge=1,
        description="Last activity ID from the previous page.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    activities, next_cursor = ActivityService.list_all(db, cursor=cursor, limit=limit)
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
    return Response(
        ok=True,
        data=CursorPage(items=items, next_cursor=next_cursor),
    )
