"""
app.models
==========

This package defines all **SQLAlchemy ORM models** representing
the database structure of the application.

Each model in this package maps directly to a database table and
defines columns, relationships, and constraints at the persistence layer.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

from .user import WafficeUser
from .user_history import UserHistory
from .user_link import UserLink
from .user_pending import UserPending

__all__ = [
    "Base",
    "WafficeUser",
    "UserLink",
    "UserHistory",
    "UserPending",
]
