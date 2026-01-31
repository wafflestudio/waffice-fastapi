from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    ok: bool = True
    data: T | None = None
    error: str | None = None
    message: str | None = None


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: int | None = None


class Website(BaseModel):
    url: str
    type: str
    description: str | None = None
