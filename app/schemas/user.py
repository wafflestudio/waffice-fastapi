from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import GraduationStatus, NotificationChannel, Qualification
from app.schemas.common import Website


class CurrentProject(BaseModel):
    """Brief project info for showing a user's current memberships."""

    id: int = Field(description="Unique project identifier")
    name: str = Field(description="Project name")

    model_config = {"from_attributes": True}


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
    generation: str = Field(
        description="Generation/cohort identifier",
        min_length=1,
        max_length=20,
        examples=["23.5"],
    )
    email: EmailStr = Field(
        description="Preferred contact email",
        examples=["user@example.com"],
    )
    graduation_status: GraduationStatus = Field(
        description="학부생, 졸업생, 휴학생, 대학원생",
    )
    qualification: Qualification = Field(
        description="Requested membership qualification; account remains pending until approval",
    )
    privacy_policy_agreed: Literal[True] = Field(
        description="Required consent to personal information collection and use",
    )
    terms_agreed: Literal[True] = Field(
        description="Required consent to Waffle Studio articles and regulations",
    )
    marketing_agreed: bool = Field(
        default=False,
        description="Optional consent to receive information by email or SMS",
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

    name: str | None = Field(
        default=None,
        description="User's display name",
        min_length=1,
        max_length=100,
    )
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
    graduation_status: GraduationStatus | None = Field(
        default=None,
        description="학부생, 졸업생, 휴학생, 대학원생",
    )
    student_id: str | None = Field(
        default=None,
        description="Student ID (e.g., 2021-14205)",
        max_length=50,
    )
    department: str | None = Field(
        default=None,
        description="Department or major",
        max_length=100,
    )
    contact_email: str | None = Field(
        default=None,
        description="Preferred contact email for notifications (defaults to login email)",
        max_length=255,
    )
    notification_channel: NotificationChannel | None = Field(
        default=None,
        description="Preferred notification channel: email, sms, or both",
    )


class UserUpdateRequest(ProfileUpdateRequest):
    """
    Request body for admin to update any user.
    Extends ProfileUpdateRequest with admin-only fields.
    """

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
    is_leader: bool | None = Field(default=None, description="Grant leader privileges")
    is_admin: bool | None = Field(default=None, description="Grant admin privileges")
    is_president: bool | None = Field(
        default=None, description="Grant president privileges"
    )
    generation: str | None = Field(
        default=None,
        description="Generation/cohort identifier",
        examples=["24.5", "25.0"],
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


# === Temporary member import ===
# Roster parsing/validation lives in app/services/roster.py; the schemas
# below are only the response shapes.
class SkippedMember(BaseModel):
    """A roster row that was not created, with a machine reason and a Korean message."""

    name: str = Field(description="Member's name from the roster")
    student_id: str = Field(description="Student ID from the roster")
    reason: str = Field(
        description=(
            "Machine-readable skip reason: "
            "'already_exists' (student_id already in the DB), "
            "'duplicate_in_request' (student_id appeared earlier in the file), "
            "'missing_student_id' / 'missing_name' (the record is missing that field), "
            "or 'invalid' (malformed, e.g. over length)"
        ),
        examples=["already_exists", "missing_student_id"],
    )
    message: str = Field(
        description="Human-readable Korean explanation for the skip",
        examples=['"김와플"의 학번을 찾을 수 없습니다.'],
    )


class TempMemberImportResult(BaseModel):
    """Summary of a temporary member import."""

    created_count: int = Field(description="Number of temporary members created")
    skipped_count: int = Field(description="Number of rows skipped")
    created: list["UserBrief"] = Field(description="The temporary members created")
    skipped: list[SkippedMember] = Field(description="Rows skipped, with reasons")


# === Response ===
class UserBrief(BaseModel):
    """Minimal user information for references in other objects."""

    id: int = Field(description="Unique user identifier")
    name: str = Field(description="User's display name")
    email: str | None = Field(
        description="User's email address (null for temporary members)"
    )
    avatar_url: str | None = Field(description="URL to profile image")

    model_config = {"from_attributes": True}


class UserDetail(BaseModel):
    """Complete user profile information."""

    id: int = Field(description="Unique user identifier")
    email: str | None = Field(
        description="User's email address (from OAuth provider; null for temporary members)",
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
    requested_qualification: Qualification | None = Field(
        description="Membership qualification requested during signup",
    )
    privacy_policy_agreed: bool = Field(
        description="Whether personal information collection and use was accepted",
    )
    terms_agreed: bool = Field(
        description="Whether Waffle Studio articles and regulations were accepted",
    )
    marketing_agreed: bool = Field(
        description="Whether email or SMS information messages were accepted",
    )
    graduation_status: str = Field(
        description=(
            "Graduation status of the user. One of [학부생, 졸업생, 휴학생, 대학원생]"
        ),
        examples=["학부생", "졸업생", "휴학생", "대학원생"],
    )
    is_leader: bool = Field(description="Whether the user has leader privileges")
    is_admin: bool = Field(description="Whether the user has admin privileges")
    is_president: bool = Field(description="Whether the user has president privileges")
    phone: str | None = Field(description="Contact phone number")
    affiliation: str | None = Field(description="Current organization or company")
    bio: str | None = Field(description="Short self-introduction")
    avatar_url: str | None = Field(description="URL to profile image")
    github_username: str | None = Field(description="GitHub username")
    slack_id: str | None = Field(description="Slack member ID")
    websites: list[Website] | None = Field(description="External websites or links")
    student_id: str | None = Field(description="Student ID (e.g., 2021-14205)")
    department: str | None = Field(description="Department or major")
    contact_email: str | None = Field(
        description="Preferred contact email for notifications"
    )
    notification_channel: NotificationChannel = Field(
        description="Preferred notification channel"
    )
    is_temporary: bool = Field(
        description=(
            "Whether this is a temporary member imported from a roster "
            "(only name and student_id populated, no OAuth identity yet)"
        ),
    )
    created_at: int = Field(
        description="Unix timestamp when user was created",
        examples=[1706745600],
    )
    current_projects: list[CurrentProject] = Field(
        default=[],
        description="Projects the user is currently a member of",
    )

    model_config = {"from_attributes": True}


# Resolve the forward reference to UserBrief used in TempMemberImportResult.
TempMemberImportResult.model_rebuild()
