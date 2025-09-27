# /controllers/user_controller.py

"""
User Controller
===============

- Author: KMSstudio
- Description:
    Contains business logic for user, pending user, and user history operations.
"""

import time

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User, UserHistory, UserPending
from app.schemas import UserPendingCreate, UserPrivilege, UserType

# -----------------------
# User Pending
# -----------------------


def create_pending_user(db: Session, data: UserPendingCreate):
    """가입 대기열에 신규 유저 추가"""
    new_pending = UserPending(
        google_id=data.google_id,
        email=data.email,
        name=data.name,
        profile_picture=data.profile_picture,
        ctime=int(time.time()),
    )
    try:
        db.add(new_pending)
        db.commit()
        db.refresh(new_pending)
        return new_pending
    except IntegrityError:
        db.rollback()
        return None


def deny_user(db: Session, payload: dict):
    pending = (
        db.query(UserPending).filter(UserPending.id == payload["pending_id"]).first()
    )
    if not pending:
        return None
    db.delete(pending)
    db.commit()
    return True


def enroll_user(db: Session, payload: dict):
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


# -----------------------
# User Info
# -----------------------


def get_user_info(db: Session, userid: int):
    user = db.query(User).filter(User.id == userid).first()
    if not user:
        return None
    histories = db.query(UserHistory).filter(UserHistory.userid == userid).all()
    return {"user": user, "history": histories}


def get_all_users(db: Session):
    return db.query(User).all()


def update_user(db: Session, payload: dict):
    user = db.query(User).filter(User.id == payload["userid"]).first()
    if not user:
        return None

    if "privilege" in payload:
        user.privilege = UserPrivilege(payload["privilege"])
    if "admin" in payload:
        user.admin = payload["admin"]

    user.mtime = int(time.time())
    db.commit()
    db.refresh(user)
    return user


def update_access_time(db: Session, userid: int):
    user = db.query(User).filter(User.id == userid).first()  # <- 변경
    if not user:
        return None
    user.atime = int(time.time())
    db.commit()
    db.refresh(user)
    return user
