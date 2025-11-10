# services/user_service.py
from sqlalchemy.orm import Session, selectinload

from app.models.user import WafficeUser
from app.models.user_link import UserLink


class UserService:
    @staticmethod
    def get_by_google(db: Session, google_id: str) -> WafficeUser | None:
        return db.query(WafficeUser).filter_by(google_id=google_id).first()

    @staticmethod
    def get_with_links(db: Session, user_id: int) -> WafficeUser | None:
        return (
            db.query(WafficeUser)
            .options(selectinload(WafficeUser.links))
            .filter(WafficeUser.id == user_id)
            .first()
        )

    @staticmethod
    def list_all(db: Session, limit: int = 100):
        return db.query(WafficeUser).limit(limit).all()

    @staticmethod
    def create(db: Session, **data) -> WafficeUser:
        user = WafficeUser(**data)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update_profile(db: Session, user: WafficeUser, updates: dict):
        for k, v in updates.items():
            setattr(user, k, v)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
