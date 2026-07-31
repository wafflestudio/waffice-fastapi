from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_admin
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
    summary="List all users' activities",
    description="Returns persisted activities for all users with offset-based pagination. Admin only.",
)
async def list_activities(
    page: int = Query(default=1, ge=1, description="Page number (1-based)."),
    size: int = Query(default=20, ge=1, le=100, description="Number of items per page."),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    activities, total = ActivityService.list_all_paged(db, page=page, size=size)
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
        data=Page(items=items, total=total, page=page, size=size),
    )
