from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.controllers import userhist_controller
from app.schemas import UserHistoryCreate

router = APIRouter(prefix="/api/userhist", tags=["user_history"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------
# User History
# -----------------------


@router.post("/userhist/create", status_code=status.HTTP_201_CREATED)
def userhist_create(data: UserHistoryCreate, db: Session = Depends(get_db)):
    result = userhist_controller.create_user_history(db, data)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "id": result.id}


@router.get("/userhist/info")
def userhist_info(id: int, db: Session = Depends(get_db)):
    result = userhist_controller.get_user_history(db, id)
    if not result:
        raise HTTPException(status_code=404, detail="History not found")
    return {"ok": True, "history": result}


@router.get("/userhist/all")
def userhist_all(db: Session = Depends(get_db)):
    histories = userhist_controller.get_all_user_histories(db)
    return {"ok": True, "histories": histories}
