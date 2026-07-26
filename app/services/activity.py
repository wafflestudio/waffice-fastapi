from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models.enums import ApprovalStatus
from app.models.request import ApprovalRequest
from app.models.user_activity import UserActivity


class ActivityService:
    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[UserActivity]:
        return (
            db.query(UserActivity)
            .options(joinedload(UserActivity.project))
            .filter(UserActivity.user_id == user_id)
            .order_by(UserActivity.start_date.desc(), UserActivity.id.desc())
            .all()
        )

    @staticmethod
    def list_all(
        db: Session, *, cursor: int | None, limit: int
    ) -> tuple[list[UserActivity], int | None]:
        """List persisted activities using the indexed primary key as a cursor."""
        query = db.query(UserActivity).options(
            joinedload(UserActivity.user),
            joinedload(UserActivity.project),
        )
        if cursor is not None:
            query = query.filter(UserActivity.id < cursor)

        items = query.order_by(UserActivity.id.desc()).limit(limit + 1).all()
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = page_items[-1].id if has_more and page_items else None
        return page_items, next_cursor

    @staticmethod
    def pending_updates_by_activity(
        db: Session, activity_ids: list[int]
    ) -> dict[int, ApprovalRequest]:
        """Return the newest pending update request for each activity."""
        if not activity_ids:
            return {}

        requests = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.deleted_at.is_(None),
                ApprovalRequest.status == ApprovalStatus.PENDING,
                ApprovalRequest.body["request_kind"].as_string() == "update",
                ApprovalRequest.body["activity_id"].as_integer().in_(activity_ids),
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .all()
        )

        pending_by_activity: dict[int, ApprovalRequest] = {}
        for approval_request in requests:
            activity_id = approval_request.body.get("activity_id")
            if isinstance(activity_id, int):
                pending_by_activity.setdefault(activity_id, approval_request)
        return pending_by_activity

    @staticmethod
    def list_pending_creates(db: Session, *, user_id: int) -> list[ApprovalRequest]:
        """List pending create requests whose target is the given user."""
        return (
            db.query(ApprovalRequest)
            .options(joinedload(ApprovalRequest.project))
            .filter(
                ApprovalRequest.deleted_at.is_(None),
                ApprovalRequest.status == ApprovalStatus.PENDING,
                ApprovalRequest.body["request_kind"].as_string() == "create",
                ApprovalRequest.body["target_user_id"].as_integer() == user_id,
            )
            .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
            .all()
        )

    @staticmethod
    def get(db: Session, activity_id: int) -> UserActivity | None:
        return db.query(UserActivity).filter(UserActivity.id == activity_id).first()

    @staticmethod
    def get_for_user(
        db: Session, *, activity_id: int | None, user_id: int
    ) -> UserActivity | None:
        if activity_id is None:
            return None
        activity = ActivityService.get(db, activity_id)
        if activity is None or activity.user_id != user_id:
            return None
        return activity

    @staticmethod
    def to_request_snapshot(activity: UserActivity) -> dict:
        return {
            "project_id": activity.project_id,
            "position": activity.position,
            "start_date": activity.start_date,
            "end_date": activity.end_date,
            "status": activity.status.value,
            "description": activity.description,
        }

    @staticmethod
    def create(db: Session, user_id: int, **data) -> UserActivity:
        activity = UserActivity(user_id=user_id, **data)
        db.add(activity)
        db.commit()
        db.refresh(activity)
        return activity

    @staticmethod
    def update(db: Session, activity: UserActivity, **data) -> UserActivity:
        for key, value in data.items():
            setattr(activity, key, value)
        db.commit()
        db.refresh(activity)
        return activity

    @staticmethod
    def delete(db: Session, activity: UserActivity) -> None:
        db.delete(activity)
        db.commit()
