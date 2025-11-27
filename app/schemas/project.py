# app/schemas/project.py
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import AnyUrl, BaseModel, Field

# =========================
# ENUM
# =========================


class ProjectStatus(str, Enum):
    active = "active"
    maintenance = "maintenance"
    ended = "ended"


class ProjectMemberRole(str, Enum):
    leader = "leader"
    member = "member"


# =========================
# PROJECT
# =========================


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    status: ProjectStatus = ProjectStatus.active
    start_date: date
    end_date: Optional[date] = None


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    status: ProjectStatus = ProjectStatus.active


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[ProjectStatus] = None


# Forward refs용 Out 타입들을 아래에서 정의하기 위해 먼저 선언
class ProjectWebsiteOut(BaseModel):
    id: int
    project_id: int
    label: Optional[str] = None
    url: AnyUrl
    kind: Optional[str] = None
    is_primary: bool = False
    ord: int = 0
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}


class ProjectMemberOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    role: ProjectMemberRole
    position: str
    start_date: date
    end_date: Optional[date] = None
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}


class Project(ProjectBase):
    id: int
    ctime: datetime
    mtime: datetime

    websites: List[ProjectWebsiteOut] = []
    members: List[ProjectMemberOut] = []

    model_config = {"from_attributes": True}


# =========================
# PROJECT WEBSITE
# =========================


class ProjectWebsiteBase(BaseModel):
    project_id: int
    label: Optional[str] = Field(None, max_length=128)
    url: AnyUrl
    kind: Optional[str] = Field(None, max_length=64)
    is_primary: bool = False
    ord: int = 0


class ProjectWebsiteCreate(ProjectWebsiteBase):
    pass


class ProjectWebsiteUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=128)
    url: Optional[AnyUrl] = None
    kind: Optional[str] = Field(None, max_length=64)
    is_primary: Optional[bool] = None
    ord: Optional[int] = None


class ProjectWebsite(ProjectWebsiteBase):
    id: int
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}


# =========================
# PROJECT MEMBER
# =========================


class ProjectMemberBase(BaseModel):
    project_id: int
    user_id: int
    role: ProjectMemberRole = ProjectMemberRole.member
    position: str = Field(..., min_length=1, max_length=32)
    start_date: date
    end_date: Optional[date] = None


class ProjectMemberCreate(ProjectMemberBase):
    pass


class ProjectMemberUpdate(BaseModel):
    role: Optional[ProjectMemberRole] = None
    position: Optional[str] = Field(None, min_length=1, max_length=32)
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectMember(ProjectMemberBase):
    id: int
    ctime: datetime
    mtime: datetime

    model_config = {"from_attributes": True}
