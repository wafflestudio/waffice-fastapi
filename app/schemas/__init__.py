"""
app.schemas
===========

This package defines **Pydantic data models (schemas)** used for validation,
serialization, and documentation of request and response bodies in FastAPI.

Unlike the `app.models` package, which contains SQLAlchemy ORM models
defining the actual database schema and relationships, the schemas here are
**pure data-transfer objects (DTOs)** that:

- Validate input data from API requests.
- Serialize ORM model instances into JSON responses.
- Enforce type constraints and field-level validation.
- Define the structure of API documentation automatically (via OpenAPI).

In short:
- `models` → database structure and persistence logic.
- `schemas` → API I/O structure and validation logic.

Each schema module corresponds to one logical entity in the system, e.g.:
`user.py`, `user_link.py`, `user_history.py`, `user_pending.py`.
"""

from .user import User, UserBase, UserCreate, UserPrivilege, UserType
from .user_history import (
    UserHistory,
    UserHistoryBase,
    UserHistoryCreate,
    UserHistoryType,
)
from .user_link import (
    UserLink,
    UserLinkBase,
    UserLinkCreate,
    UserLinkOut,
    UserLinkUpdate,
)
from .user_pending import (
    PendingDecideIn,
    PendingDecideOut,
    PendingDecision,
    UserPending,
    UserPendingBase,
    UserPendingCreate,
    UserPendingUpdate,
)

__all__ = [
    # user
    "User",
    "UserBase",
    "UserCreate",
    "UserPrivilege",
    "UserType",
    # user_link
    "UserLink",
    "UserLinkBase",
    "UserLinkCreate",
    "UserLinkUpdate",
    "UserLinkOut",
    # user_history
    "UserHistory",
    "UserHistoryBase",
    "UserHistoryCreate",
    "UserHistoryType",
    # user_pending
    "UserPending",
    "UserPendingBase",
    "UserPendingCreate",
    "UserPendingUpdate",
    "PendingDecision",
    "PendingDecideIn",
    "PendingDecideOut",
]
