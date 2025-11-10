# services/user_pending_service.py
from sqlalchemy.orm import Session

from app.models.user_pending import UserPending


class UserPendingService:
    @staticmethod
    def get_by_google(db: Session, google_id: str) -> UserPending | None:
        return db.query(UserPending).filter_by(google_id=google_id).first()

    @staticmethod
    def create(db: Session, **data) -> UserPending:
        obj = UserPending(**data)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @staticmethod
    def delete(db: Session, obj: UserPending):
        db.delete(obj)
        db.commit()
