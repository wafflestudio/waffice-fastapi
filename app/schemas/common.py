from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    """
    Standard API response wrapper.

    All API endpoints return this format for consistent client handling.
    """

    ok: bool = Field(
        default=True,
        description="Indicates whether the request was successful",
    )
    data: T | None = Field(
        default=None,
        description="Response payload. Contains the requested data on success.",
    )
    error: str | None = Field(
        default=None,
        description="Error code for programmatic error handling (e.g., 'NOT_FOUND', 'FORBIDDEN')",
    )
    message: str | None = Field(
        default=None,
        description="Human-readable message providing additional context",
    )


class CursorPage(BaseModel, Generic[T]):
    """
    Cursor-based pagination wrapper.

    Use `next_cursor` to fetch the next page of results.
    When `next_cursor` is null, there are no more items.
    """

    items: list[T] = Field(description="List of items in the current page")
    next_cursor: int | None = Field(
        default=None,
        description="Cursor for the next page. Pass this as the 'cursor' query parameter. Null if no more items.",
    )


class Website(BaseModel):
    """External website or link associated with a user or project."""

    url: str = Field(
        description="Full URL including protocol",
        examples=["https://github.com/username", "https://linkedin.com/in/username"],
    )
    type: str = Field(
        description="Type of website",
        examples=["github", "linkedin", "portfolio", "blog", "other"],
    )
    description: str | None = Field(
        default=None,
        description="Optional description of the website",
        examples=["My personal blog about tech"],
    )
