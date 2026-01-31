from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HistoryAction, UserHistory


class HistoryService:
    @staticmethod
    def log(
        db: Session,
        user_id: int,
        action: HistoryAction,
        payload: dict,
        actor_id: int | None = None,
    ) -> UserHistory:
        """Create a new history entry"""
        history = UserHistory(
            user_id=user_id, action=action, payload=payload, actor_id=actor_id
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[UserHistory]:
        """List all history entries for a user"""
        return (
            db.query(UserHistory)
            .filter(UserHistory.user_id == user_id)
            .order_by(UserHistory.created_at.desc())
            .all()
        )
