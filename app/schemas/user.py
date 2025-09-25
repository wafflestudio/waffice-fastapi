# schemas/user.py

from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserType(str, Enum):
    programmer = "programmer"
    designer = "designer"


class UserPrivilege(str, Enum):
    준회원 = "준회원"
    정회원 = "정회원"
    활동회원 = "활동회원"


class UserBase(BaseModel):
    google_id: str
    type: UserType
    privilege: UserPrivilege
    admin: int = 0
    info_phonecall: Optional[str] = None
    info_email: Optional[EmailStr] = None
    info_major: Optional[str] = None
    info_cardinal: Optional[str] = None
    info_position: Optional[str] = None
    info_work: Optional[str] = None
    info_introduce: Optional[str] = None
    info_sns1: Optional[str] = None
    info_sns2: Optional[str] = None
    info_sns3: Optional[str] = None
    info_sns4: Optional[str] = None
    id_github: Optional[str] = None
    id_slack: Optional[str] = None
    receive_email: bool = True
    receive_sms: bool = True


class UserCreate(UserBase):
    pass


class User(UserBase):
    userid: int
    atime: int
    ctime: int
    mtime: int
    time_quit: Optional[int] = None
    time_stop: Optional[int] = None

    class Config:
        orm_mode = True
