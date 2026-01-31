from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.user import UserDetail


class Token(BaseModel):
    """JWT access token for API authentication."""

    access_token: str = Field(
        description="JWT token to include in Authorization header as 'Bearer {token}'",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    token_type: str = Field(
        default="bearer",
        description="Token type, always 'bearer'",
    )


class AuthStatus(BaseModel):
    """
    Authentication status after OAuth callback.

    Status meanings:
    - `new`: User not registered. Frontend should redirect to signup flow.
    - `pending`: User registered but awaiting admin approval. Limited access.
    - `active`: User fully approved. Full access based on qualification level.
    """

    status: Literal["new", "pending", "active"] = Field(
        description="Current authentication state: 'new' (needs signup), 'pending' (awaiting approval), 'active' (approved)"
    )
    user: UserDetail | None = Field(
        default=None,
        description="User details if authenticated. Null for 'new' status.",
    )
