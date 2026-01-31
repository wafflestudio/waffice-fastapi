from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.models.enums import MemberRole, ProjectStatus
from app.schemas.common import Website
from app.schemas.user import UserBrief


# === Request ===
class MemberInput(BaseModel):
    user_id: int
    role: MemberRole
    position: str | None = Field(None, max_length=100)


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus = ProjectStatus.ACTIVE
    started_at: date
    ended_at: date | None = None
    websites: list[Website] | None = None
    members: list[MemberInput] = Field(..., min_length=1)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus | None = None
    started_at: date | None = None
    ended_at: date | None = None
    websites: list[Website] | None = None


class MemberUpdateRequest(BaseModel):
    role: MemberRole | None = None
    position: str | None = Field(None, max_length=100)


# === Response ===
class MemberDetail(BaseModel):
    id: int
    user: UserBrief
    role: MemberRole
    position: str | None
    joined_at: date | None
    left_at: date | None

    model_config = {"from_attributes": True}


class ProjectBrief(BaseModel):
    id: int
    name: str
    status: ProjectStatus
    started_at: date
    created_at: int

    model_config = {"from_attributes": True}


class ProjectDetail(ProjectBrief):
    description: str | None
    ended_at: date | None
    websites: list[Website] | None
    members: list[MemberDetail]

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def filter_active_members(cls, data):
        """Filter out inactive members"""
        if hasattr(data, "members"):
            # Filter to only active members (left_at is None)
            data.members = [m for m in data.members if m.left_at is None]
        return data
