# schemas/user.py

from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserType(str, Enum):
    programmer = "programmer"
    designer = "designer"


class UserPrivilege(str, Enum):
    associate = "associate"
    regular = "regular"
    active = "active"


class UserBase(BaseModel):
    google_id: str
    type: UserType
    privilege: UserPrivilege
    admin: int = 0
    profile_phone: Optional[str] = None
    profile_email: Optional[EmailStr] = None
    profile_major: Optional[str] = None
    profile_cardinal: Optional[str] = None
    profile_position: Optional[str] = None
    profile_work: Optional[str] = None
    profile_intro: Optional[str] = None
    profile_sns1: Optional[str] = None
    profile_sns2: Optional[str] = None
    profile_sns3: Optional[str] = None
    profile_sns4: Optional[str] = None
    id_github: Optional[str] = None
    id_slack: Optional[str] = None
    receive_email: bool = True
    receive_sms: bool = True


class UserCreate(UserBase):
    pass


class User(UserBase):
    id: int
    atime: int
    ctime: int
    mtime: int
    time_quit: Optional[int] = None
    time_stop: Optional[int] = None
    model_config = {"from_attributes": True}
