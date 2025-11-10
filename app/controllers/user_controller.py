# controllers/user_controller.py
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.schemas import PendingDecideIn
from app.services.user_pending_service import UserPendingService
from app.services.user_service import UserService


class UserController:
    # ----------------------------------------------------------
    # PUBLIC
    # ----------------------------------------------------------
    @staticmethod
    def get_status(db: Session, google_id: str):
        """
        - google_id 로 현재 상태 조회 (미등록 | 대기 | 승인)
        - 승인 시 JWT 발급 (지금은 stub)
        """
        user = UserService.get_by_google(db, google_id)
        if user:
            return {"status": "approved", "user_id": user.id, "jwt": "fake-jwt"}

        pending = UserPendingService.get_by_google(db, google_id)
        if pending:
            return {"status": "pending"}

        return {"status": "unregistered"}

    @staticmethod
    def create_pending(db: Session, google_id: str, email: str = "", name: str = ""):
        """
        승인 대기열 등록
        """
        if UserPendingService.get_by_google(db, google_id):
            raise HTTPException(status_code=400, detail="Already pending")
        return UserPendingService.create(
            db, google_id=google_id, email=email, name=name
        )

    @staticmethod
    def get_me(db: Session, user_id: int):
        """
        JWT 인증 유저의 정보 반환 (프로젝트, 히스토리 포함 예정)
        """
        user = UserService.get_with_links(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    @staticmethod
    def update_profile(db: Session, user_id: int, updates: dict):
        """
        JWT 인증 유저의 프로필 수정
        """
        user = UserService.get_with_links(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserService.update_profile(db, user, updates)

    # ----------------------------------------------------------
    # EXECUTIVE
    # ----------------------------------------------------------
    @staticmethod
    def list_all(db: Session):
        """
        모든 유저 목록 조회
        """
        return UserService.list_all(db)

    @staticmethod
    def decide_pending(db: Session, payload: PendingDecideIn):
        """
        승인 대기열의 유저를 정식 유저로 승격(accept)하거나 거절(deny)한다.
        """
        pending = UserPendingService.get_by_google(db, payload.google_id)
        if not pending:
            raise HTTPException(status_code=404, detail="Pending not found")

        # deny: pending만 제거
        if payload.decision == "deny":
            UserPendingService.delete(db, pending)
            return {"status": "denied", "removed_pending": True, "user": None}

        # accept: type/privilege 필수
        if payload.decision == "accept":
            if not payload.type or not payload.privilege:
                raise HTTPException(
                    status_code=422,
                    detail="type and privilege are required for 'accept' decision",
                )
            if UserService.get_by_google(db, pending.google_id):
                raise HTTPException(status_code=409, detail="User already exists")

            new_user = UserService.create(
                db,
                google_id=pending.google_id,
                type=(
                    payload.type.value
                    if hasattr(payload.type, "value")
                    else str(payload.type)
                ),
                privilege=(
                    payload.privilege.value
                    if hasattr(payload.privilege, "value")
                    else str(payload.privilege)
                ),
                admin=0,
            )
            UserPendingService.delete(db, pending)
            return {"status": "accepted", "removed_pending": True, "user": new_user}

        # 알 수 없는 decision
        raise HTTPException(status_code=400, detail="Invalid decision")

    @staticmethod
    def get_user_info(db: Session, user_id: int = None, google_id: str = None):
        """
        user_id 또는 google_id로 유저 상세 조회
        """
        if not user_id and not google_id:
            raise HTTPException(status_code=400, detail="user_id or google_id required")

        user = None
        if user_id:
            user = UserService.get_with_links(db, user_id)
        elif google_id:
            user = UserService.get_by_google(db, google_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return user

    @staticmethod
    def update_exec_user(db: Session, updates: list[dict]):
        """
        운영진이 여러 유저의 회원형태/정지기간 등을 수정 (stub)
        """
        return {"updated": len(updates)}
