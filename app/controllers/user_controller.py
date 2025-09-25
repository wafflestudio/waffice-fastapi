# /controllers/user_controller.py

"""
User Controller
===============

- Author: KMSstudio
- Description:
    Contains business logic for user, pending user, and user history operations.
"""

import time

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.schemas import UserHistoryCreate, UserPendingCreate, UserPrivilege, UserType
from app.models import User, UserHistory, UserPending

# -----------------------
# User Pending
# -----------------------


def create_pending_user(db: Session, data: UserPendingCreate):
    """가입 대기열에 신규 유저 추가"""
    new_pending = UserPending(google_id=data.google_id, email=data.email,name=data.name, profile_picture=data.profile_picture, ctime=int(time.time()), )
    try:
        db.add(new_pending)
        db.commit()
        db.refresh(new_pending)
        return new_pending
    except IntegrityError:
        db.rollback()
        return None


def enroll_user(db: Session, payload: dict):
    """가입 대기열 유저를 정식 회원으로 등록"""
    pending = (
        db.query(UserPending).filter(UserPending.id == payload["pending_id"]).first()
    )
    if not pending:
        return None
    exists = db.query(User).filter(User.google_id == pending.google_id).first()
    if exists:
        return "conflict"

    new_user = User(
        google_id=pending.google_id,
        type=UserType(payload["type"]),
        privilege=UserPrivilege(payload["privilege"]),
        admin=0,
        atime=int(time.time()),
        ctime=int(time.time()),
        mtime=int(time.time()),
    )
    try:
        db.add(new_user)
        db.delete(pending)
        db.commit()
        db.refresh(new_user)
        return new_user
    except Exception:
        db.rollback()
        return None


def deny_user(db: Session, payload: dict):
    """가입 대기열 거절"""
    pending = (
        db.query(UserPending).filter(UserPending.id == payload["pending_id"]).first()
    )
