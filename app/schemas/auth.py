from typing import Literal

from pydantic import BaseModel, EmailStr, Field

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
    auth_token: str = Field(
        description="Temporary auth token for signin/signup. Valid for 10 minutes.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )


class AuthResult(BaseModel):
    """
    Authentication result after signin/signup.

    Token is set via HttpOnly cookie, not returned in response body.
    """

    status: Literal["pending", "active"] = Field(
        description="User status: 'pending' (awaiting approval), 'active' (approved)"
    )
    user: UserDetail = Field(description="User details")


class SigninRequest(BaseModel):
    """Request body for signing in with an auth token."""

    auth_token: str = Field(
        description="Temporary auth token received from OAuth callback",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )


class GoogleTokenRequest(BaseModel):
    """Request body for exchanging Google authorization code for auth token."""

    code: str = Field(
        description="Authorization code received from Google OAuth callback",
        examples=["4/0AX4XfWh..."],
    )
    redirect_uri: str = Field(
        description="The redirect URI used in the OAuth flow (must match the one used to get the code)",
        examples=["https://myapp.com/auth/callback"],
    )


class DevSigninRequest(BaseModel):
    """Request body for development-only signin. Only available in local/dev environments."""

    email: EmailStr = Field(
        description="User email for dev signin",
        examples=["admin@dev.local"],
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="User name for dev signin",
        examples=["Admin User"],
    )
    is_admin: bool = Field(
        default=False,
        description="Whether the user should be an admin",
    )
    qualification: Literal["pending", "associate", "regular", "active"] = Field(
        default="active",
        description="User qualification level",
    )
