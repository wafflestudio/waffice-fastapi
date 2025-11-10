# schemas/user_link.py

from datetime import datetime
from typing import Optional

from pydantic import AnyUrl, BaseModel, Field


class UserLinkBase(BaseModel):
    user_id: int
    kind: str = Field(
        ..., min_length=1, max_length=64
    )  # 'github','website','blog','twitter', ...
    label: Optional[str] = Field(None, max_length=128)
    url: AnyUrl
    visible: bool = True
    ord: int = 0


class UserLinkCreate(UserLinkBase):
    pass


class UserLinkOut(BaseModel):
    id: int
    kind: str
    label: Optional[str] = None
    url: AnyUrl
    visible: bool
    ord: int
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}


class UserLinkUpdate(BaseModel):
    kind: Optional[str] = Field(None, min_length=1, max_length=64)
    label: Optional[str] = Field(None, max_length=128)
    url: Optional[AnyUrl] = None
    visible: Optional[bool] = None
    ord: Optional[int] = None


class UserLink(UserLinkBase):
    id: int
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}
