# routes/user_route.py

from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_db
from app.controllers.user_controller import UserController
from app.schemas import (
    PendingDecideIn,
    PendingDecideOut,
    User,
    UserPending,
    UserPendingCreate,
)
from app.utils.jwt_auth import get_current_user

router = APIRouter(prefix="/api", tags=["User"])

CurrentUserPayload = Annotated[Dict[str, Any], Depends(get_current_user)]


# ==========================================================
# PUBLIC USER ROUTES
# ==========================================================


@router.get("/user/status")
def user_status(google_id: str, db: Session = Depends(get_db)):
    return UserController.get_status(db, google_id)


@router.post("/user/create", response_model=UserPending)
def user_create_pending(payload: UserPendingCreate, db: Session = Depends(get_db)):
    return UserController.create_pending(
        db,
        google_id=payload.google_id,
        email=payload.email,
        name=payload.name,
        # github는 저장 안 하더라도 스키마에서 받아 두면 422를 막을 수 있음
    )


@router.get("/user/me", response_model=User)
def user_me(
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return UserController.get_me(db, user_id)


@router.patch("/user/update", response_model=User)
def update_profile(
    updates: dict,
    db: Session = Depends(get_db),
    user_payload: CurrentUserPayload = None,
):
    user_id = int(user_payload["user_id"])
    return UserController.update_profile(db, user_id, updates)


# ==========================================================
# EXECUTIVE USER ROUTES
# ==========================================================


@router.get("/exct/user/all")
def get_all_users(db: Session = Depends(get_db)):
    return UserController.list_all(db)


@router.post("/exct/user/decide", response_model=PendingDecideOut)
def decide_pending(payload: PendingDecideIn, db: Session = Depends(get_db)):
    return UserController.decide_pending(db, payload)


@router.get("/exct/user/info")
def get_user_info(
    user_id: int = None, google_id: str = None, db: Session = Depends(get_db)
):
    return UserController.get_user_info(db, user_id, google_id)


@router.patch("/exct/user/update")
def update_exec_user(updates: list[dict], db: Session = Depends(get_db)):
    return UserController.update_exec_user(db, updates)
