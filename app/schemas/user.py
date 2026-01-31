from pydantic import BaseModel

from app.models.enums import Qualification
from app.schemas.common import Website


# === Request ===
class SignupRequest(BaseModel):
    name: str
    phone: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    github_username: str | None = None


class ProfileUpdateRequest(BaseModel):
    phone: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    github_username: str | None = None
    slack_id: str | None = None
    websites: list[Website] | None = None


class UserUpdateRequest(ProfileUpdateRequest):
    """Admin용"""

    name: str | None = None
    qualification: Qualification | None = None
    is_admin: bool | None = None


class ApproveRequest(BaseModel):
    qualification: Qualification


# === Response ===
class UserBrief(BaseModel):
    id: int
    name: str
    email: str
    avatar_url: str | None

    model_config = {"from_attributes": True}


class UserDetail(BaseModel):
    id: int
    email: str
    name: str
    generation: str
    qualification: Qualification
    is_admin: bool
    phone: str | None
    affiliation: str | None
    bio: str | None
    avatar_url: str | None
    github_username: str | None
    slack_id: str | None
    websites: list[Website] | None
    created_at: int

    model_config = {"from_attributes": True}
