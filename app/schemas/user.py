from pydantic import BaseModel, Field

from app.models.enums import Qualification
from app.schemas.common import Website


# === Request ===
class SignupRequest(BaseModel):
    """Request body for completing user registration after OAuth."""

    auth_token: str = Field(
        description="Temporary auth token received from OAuth callback",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    name: str = Field(
        description="User's display name",
        min_length=1,
        max_length=100,
        examples=["John Doe"],
    )
    phone: str | None = Field(
        default=None,
        description="Contact phone number",
        examples=["010-1234-5678"],
    )
    affiliation: str | None = Field(
        default=None,
        description="Current organization or company",
        examples=["Waffle Studio", "Seoul National University"],
    )
    bio: str | None = Field(
        default=None,
        description="Short self-introduction",
        max_length=500,
        examples=["Backend developer interested in distributed systems"],
    )
    github_username: str | None = Field(
        default=None,
        description="GitHub username (without @)",
        examples=["octocat"],
    )


class ProfileUpdateRequest(BaseModel):
    """Request body for updating own profile. All fields are optional."""

    phone: str | None = Field(
        default=None,
        description="Contact phone number",
        examples=["010-1234-5678"],
    )
    affiliation: str | None = Field(
        default=None,
        description="Current organization or company",
        examples=["Waffle Studio"],
    )
    bio: str | None = Field(
        default=None,
        description="Short self-introduction",
        max_length=500,
    )
    avatar_url: str | None = Field(
        default=None,
        description="URL to profile image",
        examples=["https://example.com/avatar.jpg"],
    )
    github_username: str | None = Field(
        default=None,
        description="GitHub username (without @)",
        examples=["octocat"],
    )
    slack_id: str | None = Field(
        default=None,
        description="Slack member ID for mentions",
        examples=["U01ABC123DE"],
    )
    websites: list[Website] | None = Field(
        default=None,
        description="List of external websites or social links",
    )


class UserUpdateRequest(ProfileUpdateRequest):
    """
    Request body for admin to update any user.
    Extends ProfileUpdateRequest with admin-only fields.
    """

    name: str | None = Field(
        default=None,
        description="User's display name",
        min_length=1,
        max_length=100,
    )
    qualification: Qualification | None = Field(
        default=None,
        description=(
            "Membership qualification level. "
            "PENDING: awaiting approval, "
            "ASSOCIATE: approved but limited access, "
            "REGULAR: standard member, "
            "ACTIVE: fully active member with all privileges"
        ),
    )
    is_admin: bool | None = Field(
        default=None,
        description="Whether user has admin privileges",
    )


class ApproveRequest(BaseModel):
    """Request body for approving a pending user."""

    qualification: Qualification = Field(
        description=(
            "Target qualification level (cannot be PENDING). "
            "ASSOCIATE: basic member, "
            "REGULAR: standard member, "
            "ACTIVE: fully active member"
        )
    )


# === Response ===
class UserBrief(BaseModel):
    """Minimal user information for references in other objects."""

    id: int = Field(description="Unique user identifier")
    name: str = Field(description="User's display name")
    email: str = Field(description="User's email address")
    avatar_url: str | None = Field(description="URL to profile image")

    model_config = {"from_attributes": True}


class UserDetail(BaseModel):
    """Complete user profile information."""

    id: int = Field(description="Unique user identifier")
    email: str = Field(
        description="User's email address (from OAuth provider)",
        examples=["user@example.com"],
    )
    name: str = Field(
        description="User's display name",
        examples=["John Doe"],
    )
    generation: str = Field(
        description="Generation/cohort identifier",
        examples=["24.5", "25.0"],
    )
    qualification: Qualification = Field(
        description=(
            "Membership level determining access. "
            "PENDING < ASSOCIATE < REGULAR < ACTIVE"
        )
    )
    is_admin: bool = Field(
        description="Whether user has admin privileges for user/project management"
    )
    phone: str | None = Field(description="Contact phone number")
    affiliation: str | None = Field(description="Current organization or company")
    bio: str | None = Field(description="Short self-introduction")
    avatar_url: str | None = Field(description="URL to profile image")
    github_username: str | None = Field(description="GitHub username")
    slack_id: str | None = Field(description="Slack member ID")
    websites: list[Website] | None = Field(description="External websites or links")
    created_at: int = Field(
        description="Unix timestamp when user was created",
        examples=[1706745600],
    )

    model_config = {"from_attributes": True}
