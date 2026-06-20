from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.enums import AuditAction


class AuditLogService:
    @staticmethod
    def log(
        db: Session,
        user_id: int,
        action: AuditAction,
        payload: dict,
        actor_id: int | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id, action=action, payload=payload, actor_id=actor_id
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> list[AuditLog]:
        return (
            db.query(AuditLog)
            .filter(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .all()
        )
