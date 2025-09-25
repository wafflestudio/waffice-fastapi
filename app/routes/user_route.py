# /routes/user_route.py

"""
User and UserHistory Routes
===========================

- Author: KMSstudio
- Description:
    Provides REST API endpoints for managing users, pending users,
    and user history records.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.controllers import user_controller
from app.schemas import (
    User,
    UserCreate,
    UserHistory,
    UserHistoryCreate,
    UserPending,
    UserPendingCreate,
)

router = APIRouter(prefix="/api", tags=["user"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------
# User Pending
# -----------------------


@router.post("/user/create", status_code=status.HTTP_201_CREATED)
def create_pending_user(data: UserPendingCreate, db: Session = Depends(get_db)):
    user = user_controller.create_pending_user(db, data)
    if not user:
        raise HTTPException(status_code=409, detail="Conflict: already exists")
    return {"ok": True, "id": user.id, "ctime": user.ctime}


@router.post("/user/enroll", status_code=status.HTTP_201_CREATED)
def enroll_user(payload: dict, db: Session = Depends(get_db)):
    result = user_controller.enroll_user(db, payload)
    if not result:
        raise HTTPException(status_code=404, detail="Pending user not found")
    if result == "conflict":
        raise HTTPException(status_code=409, detail="Conflict: already enrolled")
    return {"ok": True, "userid": result.userid}


@router.post("/user/deny")
def deny_user(payload: dict, db: Session = Depends(get_db)):
    result = user_controller.deny_user(db, payload)
    if not result:
        raise HTTPException(status_code=404, detail="Pending user not found")
    return {"ok": True, "status": "거절"}


# -----------------------
# User
# -----------------------


@router.get("/user/info")
def user_info(userid: int, db: Session = Depends(get_db)):
    result = user_controller.get_user_info(db, userid)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "user": result["user"], "history": result["history"]}


@router.get("/user/all")
def user_all(db: Session = Depends(get_db)):
    users = user_controller.get_all_users(db)
    return {"ok": True, "users": users}


@router.post("/user/update")
def user_update(payload: dict, db: Session = Depends(get_db)):
    result = user_controller.update_user(db, payload)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"ok": True, "userid": payload["userid"]}


@router.post("/user/access")
def user_access(payload: dict, db: Session = Depends(get_db)):
    result = user_controller.update_access_time(db, payload["userid"])
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "atime": result.atime}
