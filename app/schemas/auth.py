from typing import Literal

from pydantic import BaseModel

from app.schemas.user import UserDetail


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthStatus(BaseModel):
    status: Literal["new", "pending", "active"]
    user: UserDetail | None = None
