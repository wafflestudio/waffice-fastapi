# app/schemas/user.py
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .user_link import UserLinkOut


# --------------------------------------------------------
# ENUMS
# --------------------------------------------------------
class UserType(str, Enum):
    programmer = "programmer"
    designer = "designer"


class UserPrivilege(str, Enum):
    associate = "associate"
    regular = "regular"
    active = "active"


# --------------------------------------------------------
# BASE
# --------------------------------------------------------
class UserBase(BaseModel):
    google_id: str
    type: UserType
    privilege: UserPrivilege
    admin: int = Field(0, ge=0, le=2)

    profile_phone: Optional[str] = None
    profile_email: Optional[EmailStr] = None
    profile_major: Optional[str] = None
    profile_cardinal: Optional[str] = None
    profile_position: Optional[str] = None
    profile_work: Optional[str] = None
    profile_intro: Optional[str] = None

    id_github: Optional[str] = None
    id_slack: Optional[str] = None
    receive_email: bool = True
    receive_sms: bool = True


# --------------------------------------------------------
# RESPONSE MODEL
# --------------------------------------------------------
class User(UserBase):
    id: int
    ctime: datetime
    mtime: datetime
    time_quit: Optional[datetime] = None
    time_stop: Optional[datetime] = None

    links: List[UserLinkOut] = []

    model_config = {"from_attributes": True}


# --------------------------------------------------------
# CREATE MODEL (REQUEST BODY)
# --------------------------------------------------------
class UserCreate(BaseModel):
    google_id: str
    type: UserType
    privilege: UserPrivilege = UserPrivilege.associate
    admin: int = 0

    profile_email: Optional[EmailStr] = None
    profile_major: Optional[str] = None
    profile_cardinal: Optional[str] = None
    profile_position: Optional[str] = None
    profile_work: Optional[str] = None
