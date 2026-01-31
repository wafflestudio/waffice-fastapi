from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.models.enums import MemberRole, ProjectStatus
from app.schemas.common import Website
from app.schemas.user import UserBrief


# === Request ===
class MemberInput(BaseModel):
    """Input for adding or specifying a project member."""

    user_id: int = Field(description="ID of the user to add as member")
    role: MemberRole = Field(
        description="Member's role: 'leader' (can manage project) or 'member' (regular participant)"
    )
    position: str | None = Field(
        default=None,
        max_length=100,
        description="Member's position or responsibility in the project",
        examples=["Backend Developer", "Project Manager", "Designer"],
    )


class ProjectCreateRequest(BaseModel):
    """Request body for creating a new project."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Project name",
        examples=["Waffle App", "Internal Dashboard"],
    )
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Detailed project description. Supports markdown.",
        examples=["A mobile app for ordering waffles with real-time tracking."],
    )
    status: ProjectStatus = Field(
        default=ProjectStatus.ACTIVE,
        description=(
            "Project status: "
            "'active' (ongoing development), "
            "'maintenance' (stable, minimal updates), "
            "'ended' (completed or discontinued)"
        ),
    )
    started_at: date = Field(
        description="Project start date",
        examples=["2024-01-15"],
    )
    ended_at: date | None = Field(
        default=None,
        description="Project end date. Null for ongoing projects.",
        examples=["2024-06-30"],
    )
    websites: list[Website] | None = Field(
        default=None,
        description="Project-related links (repository, demo, documentation)",
    )
    members: list[MemberInput] = Field(
        min_length=1,
        description="Initial project members. Must include at least one leader.",
    )


class ProjectUpdateRequest(BaseModel):
    """Request body for updating project details. All fields are optional."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Project name",
    )
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Detailed project description",
    )
    status: ProjectStatus | None = Field(
        default=None,
        description="Project status: 'active', 'maintenance', or 'ended'",
    )
    started_at: date | None = Field(
        default=None,
        description="Project start date",
    )
    ended_at: date | None = Field(
        default=None,
        description="Project end date",
    )
    websites: list[Website] | None = Field(
        default=None,
        description="Project-related links",
    )


class MemberUpdateRequest(BaseModel):
    """Request body for updating a project member's role or position."""

    role: MemberRole | None = Field(
        default=None,
        description="New role: 'leader' or 'member'. Cannot demote the last leader.",
    )
    position: str | None = Field(
        default=None,
        max_length=100,
        description="New position or responsibility",
    )


# === Response ===
class MemberDetail(BaseModel):
    """Project member information including user details and role."""

    id: int = Field(description="Unique membership record identifier")
    user: UserBrief = Field(description="Member's user information")
    role: MemberRole = Field(
        description="Member's role: 'leader' (project manager) or 'member' (participant)"
    )
    position: str | None = Field(
        description="Member's position or responsibility in the project"
    )
    joined_at: date | None = Field(description="Date when member joined the project")
    left_at: date | None = Field(
        description="Date when member left the project. Null for active members."
    )

    model_config = {"from_attributes": True}


class ProjectBrief(BaseModel):
    """Summary project information for list views."""

    id: int = Field(description="Unique project identifier")
    name: str = Field(description="Project name")
    status: ProjectStatus = Field(
        description="Current status: 'active', 'maintenance', or 'ended'"
    )
    started_at: date = Field(description="Project start date")
    created_at: int = Field(
        description="Unix timestamp when project record was created"
    )

    model_config = {"from_attributes": True}


class ProjectDetail(ProjectBrief):
    """Complete project information including members."""

    description: str | None = Field(description="Detailed project description")
    ended_at: date | None = Field(
        description="Project end date. Null for ongoing projects."
    )
    websites: list[Website] | None = Field(description="Project-related links")
    members: list[MemberDetail] = Field(
        description="Active project members (excludes members who have left)"
    )

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def filter_active_members(cls, data):
        """Filter out inactive members"""
        if hasattr(data, "members"):
            # Filter to only active members (left_at is None)
            data.members = [m for m in data.members if m.left_at is None]
        return data
