from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import SessionLocal
from app.controllers import user_controller
from app.schemas.user import User, UserCreate

router = APIRouter(prefix="/users", tags=["users"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=list[User])
def list_users(db: Session = Depends(get_db)):
    return user_controller.list_users(db)


@router.post("/", response_model=User)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    return user_controller.create_user(db, user)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    return user_controller.delete_user(db, user_id)
