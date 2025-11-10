# schemas/user_pending.py

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr

from app.schemas.user import User, UserPrivilege, UserType


class UserPendingBase(BaseModel):
    google_id: str
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    github: Optional[str] = None
    profile_picture: Optional[str] = None


class UserPendingCreate(BaseModel):
    google_id: str
    email: EmailStr
    name: str
    github: Optional[str] = None  # 테스트에서 오는 필드


class UserPendingUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    github: Optional[str] = None
    profile_picture: Optional[str] = None


class UserPending(UserPendingBase):
    id: int
    ctime: datetime

    model_config = {"from_attributes": True}


class PendingDecision(str, Enum):
    accept = "accept"
    deny = "deny"


class PendingDecideIn(BaseModel):
    google_id: str
    decision: PendingDecision
    type: Optional[UserType] = None
    privilege: Optional[UserPrivilege] = None


class PendingDecideOut(BaseModel):
    status: Literal["accepted", "denied"]
    removed_pending: bool = True
    user: Optional[User] = None
