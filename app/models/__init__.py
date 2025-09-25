# /models/__init__.py

"""
Models Package
==============

This package contains all SQLAlchemy ORM model definitions used in the project.

- Author: KMSstudio
- Description:
    Each file in this package represents one or more database tables
    mapped to Python classes. These models define the schema and
    relationships for the system's database layer.
"""

from .user import User
from .user_history import UserHistory

__all__ = ["User", "UserHistory"]
