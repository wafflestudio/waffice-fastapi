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
    def get_by_student_id(db: Session, student_id: str) -> User | None:
        """Get user by student ID (excluding soft-deleted users)"""
        return (
            db.query(User)
            .filter(and_(User.student_id == student_id, User.deleted_at.is_(None)))
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
        """
        List users awaiting admin approval (excluding soft-deleted users).

        Temporary members (is_temporary=True) also default to qualification=PENDING
        but are roster placeholders, not OAuth signups awaiting approval, so they
        are excluded to keep this approval queue uncluttered.
        """
        return (
            db.query(User)
            .filter(
                and_(
                    User.qualification == Qualification.PENDING,
                    User.is_temporary.is_(False),
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
    def bulk_create_temporary(
        db: Session, members: list[tuple[str, str]]
    ) -> tuple[list[User], list[tuple[str, str, str]]]:
        """
        Create temporary members from roster rows in a single transaction.

        Each row is a (name, student_id) pair. A row is skipped (not created) if:
        - its student_id already belongs to a non-deleted user ("already_exists"), or
        - the same student_id appeared earlier in this batch ("duplicate_in_request").

        Temporary members are created with only name and student_id populated;
        email is NULL and all other columns fall back to their model defaults
        (qualification=PENDING, role=MEMBER, etc.).

        Returns (created_users, skipped) where skipped is a list of
        (name, student_id, reason).
        """
        created: list[User] = []
        skipped: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        for name, student_id in members:
            name = name.strip()
            student_id = student_id.strip()

            if student_id in seen:
                skipped.append((name, student_id, "duplicate_in_request"))
                continue
            seen.add(student_id)

            if UserService.get_by_student_id(db, student_id):
                skipped.append((name, student_id, "already_exists"))
                continue

            user = User(name=name, student_id=student_id, is_temporary=True)
            db.add(user)
            created.append(user)

        db.commit()
        for user in created:
            db.refresh(user)
        return created, skipped

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
