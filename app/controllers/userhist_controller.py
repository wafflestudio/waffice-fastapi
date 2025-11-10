# /controllers/userhist_controller.py

"""
User History Controller
=======================

- Author: KMSstudio
- Description:
    Contains business logic for user history operations.
"""

from sqlalchemy.orm import Session

from app.models import User, UserHistory
from app.schemas import UserHistoryCreate

# -----------------------
# User History
# -----------------------


def create_user_history(db: Session, data: UserHistoryCreate):
    """새로운 userHistory 생성"""
    user = db.query(User).filter(User.id == data.userid).first()
    if not user:
        return None

    history = UserHistory(
        userid=data.userid,
        type=data.type,
        description=data.description,
        curr_privilege=data.curr_privilege,
        curr_time_stop=data.curr_time_stop,
        prev_privilege=data.prev_privilege,
        prev_time_stop=data.prev_time_stop,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def get_user_history(db: Session, history_id: int):
    """특정 userHistory 조회"""
    history = db.query(UserHistory).filter(UserHistory.id == history_id).first()
    if not history:
        return None
    return history


def get_all_user_histories(db: Session):
    """전체 userHistory 조회"""
    return db.query(UserHistory).all()
