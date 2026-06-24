from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user_activity import UserActivity


class ActivityService:
    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[UserActivity]:
        return (
            db.query(UserActivity)
            .filter(UserActivity.user_id == user_id)
            .order_by(UserActivity.start_date.desc())
            .all()
        )

    @staticmethod
    def get(db: Session, activity_id: int) -> UserActivity | None:
        return db.query(UserActivity).filter(UserActivity.id == activity_id).first()

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
