from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    GraduationStatus,
    NotificationChannel,
    Qualification,
    UserRole,
)
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
    role: UserRole | None = Field(
        default=None,
        description="User role: member, leader, admin, or admin_and_leader",
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
# Zero-width / format characters that str.strip() does NOT treat as whitespace
# but render as blank (e.g. a BOM prepended by an Excel/CSV export). Trimmed from
# value ends so they cannot pass the blank check or corrupt the student_id key.
# ZWSP, ZWNJ, ZWJ, word joiner, BOM/ZWNBSP, soft hyphen.
_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\u2060\ufeff\u00ad"


class TempMemberInput(BaseModel):
    """A single roster row to import as a temporary member."""

    name: str = Field(
        description="Member's name",
        min_length=1,
        max_length=100,
        examples=["홍길동"],
    )
    student_id: str = Field(
        description="Student ID (e.g., 2021-14205). Used to match existing members.",
        min_length=1,
        max_length=50,
        examples=["2021-14205"],
    )

    @field_validator("name", "student_id")
    @classmethod
    def _strip_and_require_non_blank(cls, value: str) -> str:
        """
        Normalize by stripping surrounding whitespace and reject blank values.

        Pydantic's min_length check runs on the raw input, so a whitespace-only
        string (e.g. "   ") would otherwise pass min_length=1 and then collapse
        to an empty string downstream. Stripping here makes the stored value and
        the student_id match key consistent, and a blank result yields a 422.

        Zero-width / format characters (e.g. a BOM from an Excel export) are
        trimmed too, since str.strip() does not treat them as whitespace; the
        trailing .strip() removes any whitespace they were wrapping.
        """
        stripped = value.strip().strip(_ZERO_WIDTH_CHARS).strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TempMemberImportRequest(BaseModel):
    """
    Request body for bulk-importing a member roster as temporary members.

    The frontend parses the uploaded Excel file and sends the rows as JSON.
    """

    members: list[TempMemberInput] = Field(
        description="Roster rows. Duplicates (by student_id) are skipped.",
        min_length=1,
        max_length=2000,
    )


class SkippedMember(BaseModel):
    """A roster row that was not created, with the reason."""

    name: str = Field(description="Member's name from the roster")
    student_id: str = Field(description="Student ID from the roster")
    reason: str = Field(
        description=(
            "Why the row was skipped: "
            "'already_exists' (a member with this student_id is already in the DB) "
            "or 'duplicate_in_request' (the student_id appeared earlier in this request)"
        ),
        examples=["already_exists", "duplicate_in_request"],
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
    graduation_status: str = Field(
        description=("Graduation status of the user. One of [학부생, 졸업생, 휴학생, 대학원생]"),
        examples=["학부생", "졸업생", "휴학생", "대학원생"],
    )
    role: UserRole = Field(
        description="User role determining access level: member, leader, admin, or admin_and_leader"
    )
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

    model_config = {"from_attributes": True}


# Resolve the forward reference to UserBrief used in TempMemberImportResult.
TempMemberImportResult.model_rebuild()
