# app/routes/userhist_route.py
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_db
from app.models.user_history import UserHistory as UserHistoryModel
from app.schemas import UserHistory, UserHistoryCreate, UserHistoryType

router = APIRouter(tags=["UserHistory"])


# ==========================================================
# PUBLIC ROUTES
# ==========================================================


@router.get("/api/userhist/me", response_model=list[UserHistory])
def get_my_histories(db: Session = Depends(get_db)):
    """
    JWT 인증 유저의 개인 이력 조회
    (지금은 JWT 인증 생략, 테스트용 user_id=1)
    """
    user_id = 1
    histories = (
        db.query(UserHistoryModel)
        .filter(UserHistoryModel.user_id == user_id)
        .order_by(UserHistoryModel.ctime.desc())
        .all()
    )
    return histories


# ==========================================================
# EXECUTIVE ROUTES
# ==========================================================


@router.get("/api/exct/userhist/all", response_model=list[UserHistory])
def get_all_histories(db: Session = Depends(get_db)):
    """
    전체 유저 이력 조회 (운영진용)
    """
    histories = db.query(UserHistoryModel).order_by(UserHistoryModel.ctime.desc()).all()
    return histories


@router.get("/api/exct/userhist/{user_id}", response_model=list[UserHistory])
def get_user_history(user_id: int, db: Session = Depends(get_db)):
    """
    특정 유저의 이력 조회 (운영진용)
    """
    histories = (
        db.query(UserHistoryModel)
        .filter(UserHistoryModel.user_id == user_id)
        .order_by(UserHistoryModel.ctime.desc())
        .all()
    )
    return histories


@router.post("/api/exct/userhist/create", response_model=UserHistory)
def create_user_history(payload: UserHistoryCreate, db: Session = Depends(get_db)):
    """
    새로운 유저 이력 추가 (운영진용)
    - event_type: join / left / discipline / project_join / project_left
    """
    new_history = UserHistoryModel(
        user_id=payload.user_id,
        event_type=(
            payload.event_type.value
            if hasattr(payload.event_type, "value")
            else payload.event_type
        ),
        description=payload.description,
        prev_json=payload.prev_json,
        curr_json=payload.curr_json,
        operated_by=payload.operated_by,
        ctime=datetime.now(),
    )
    db.add(new_history)
    db.commit()
    db.refresh(new_history)
    return new_history


@router.delete("/api/exct/userhist/{history_id}")
def delete_user_history(history_id: int, db: Session = Depends(get_db)):
    """
    특정 유저 이력 삭제 (운영진용)
    """
    target = (
        db.query(UserHistoryModel).filter(UserHistoryModel.id == history_id).first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="UserHistory not found")
    db.delete(target)
    db.commit()
    return {"status": "deleted", "id": history_id}
