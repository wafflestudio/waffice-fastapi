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
    next_cursor: int | str | None = Field(
        default=None,
        description=(
            "Cursor for the next page. Pass this as the 'cursor' query parameter. "
            "Null if no more items. Simple id-based cursors are ints; composite "
            "keyset cursors are opaque numeric strings (to survive round-tripping "
            "through JS clients, whose Number type loses precision above 2^53-1)."
        ),
    )


class Page(BaseModel, Generic[T]):
    """
    Offset-based pagination wrapper.

    Use `page` and `size` query parameters to navigate pages.
    `total` is the total number of items matching the query.
    """

    items: list[T] = Field(description="List of items in the current page")
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(description="Current page number (1-based)")
    size: int = Field(description="Number of items per page")


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
