from __future__ import annotations

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import Qualification, User


class UserService:
    @staticmethod
    def get(db: Session, user_id: int) -> User | None:
        """Get user by ID (excluding soft-deleted users)"""
        return (
            db.query(User)
            .filter(and_(User.id == user_id, User.deleted_at.is_(None)))
            .first()
        )

    @staticmethod
    def get_by_google_id(db: Session, google_id: str) -> User | None:
        """Get user by Google ID (excluding soft-deleted users)"""
        return (
            db.query(User)
            .filter(and_(User.google_id == google_id, User.deleted_at.is_(None)))
            .first()
        )

    @staticmethod
    def get_by_email(db: Session, email: str) -> User | None:
        """Get user by email (excluding soft-deleted users)"""
        return (
            db.query(User)
            .filter(and_(User.email == email, User.deleted_at.is_(None)))
            .first()
        )

    @staticmethod
    def list(
        db: Session, *, cursor: int | None = None, limit: int = 20
    ) -> tuple[list[User], int | None]:
        """
        List users with cursor-based pagination (excluding soft-deleted users).
        Returns (items, next_cursor)
        """
        query = db.query(User).filter(User.deleted_at.is_(None))

        if cursor is not None:
            query = query.filter(User.created_at < cursor)

        query = query.order_by(User.created_at.desc()).limit(limit + 1)
        users = query.all()

        has_more = len(users) > limit
        if has_more:
            users = users[:limit]

        next_cursor = users[-1].created_at if has_more and users else None
        return users, next_cursor

    @staticmethod
    def list_pending(db: Session) -> list[User]:
        """List all pending users (excluding soft-deleted users)"""
        return (
            db.query(User)
            .filter(
                and_(
                    User.qualification == Qualification.PENDING,
                    User.deleted_at.is_(None),
                )
            )
            .order_by(User.created_at.desc())
            .all()
        )

    @staticmethod
    def create(db: Session, **data) -> User:
        """Create a new user"""
        user = User(**data)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def update(db: Session, user: User, **data) -> User:
        """Update user with provided data"""
        for key, value in data.items():
            if value is not None:
                setattr(user, key, value)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete(db: Session, user: User) -> None:
        """Soft delete a user by setting deleted_at"""
        import time

        user.deleted_at = int(time.time())
        db.commit()
