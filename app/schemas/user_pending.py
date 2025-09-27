from typing import Optional

from pydantic import BaseModel, EmailStr


class UserPendingBase(BaseModel):
    google_id: str
    email: EmailStr
    name: str
    profile_picture: Optional[str] = None


class UserPendingCreate(UserPendingBase):
    pass


class UserPending(UserPendingBase):
    id: int
    ctime: int

    model_config = {"from_attributes": True}
