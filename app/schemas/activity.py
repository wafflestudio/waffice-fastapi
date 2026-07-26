from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ActivityStatus
from app.schemas.user import UserBrief


class ActivityHistoryStatus(str, Enum):
    CREATE_PENDING = "create_pending"
    UPDATE_PENDING = "update_pending"
    ACTIVE = "active"


class ActivityCreateRequest(BaseModel):
    project_id: int = Field(description="Project ID this activity belongs to")
    position: str = Field(description="Role or position in the project", max_length=100)
    start_date: int = Field(description="Activity start date (Unix timestamp)")
    end_date: int | None = Field(
        default=None, description="Activity end date (Unix timestamp). Null if ongoing."
    )
    status: ActivityStatus = Field(
        default=ActivityStatus.ACTIVE, description="활동 중 or 비활동"
    )
    description: str | None = Field(default=None, description="Additional notes")


class ActivityUpdateRequest(BaseModel):
    project_id: int | None = Field(default=None)
    position: str | None = Field(default=None, max_length=100)
    start_date: int | None = Field(default=None)
    end_date: int | None = Field(default=None)
    status: ActivityStatus | None = Field(default=None)
    description: str | None = Field(default=None)

    @model_validator(mode="after")
    def reject_null_on_required_fields(self):
        for field in ("project_id", "position", "start_date", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ActivityDetail(BaseModel):
    id: int
    user_id: int
    project_id: int | None
    project_name: str | None
    position: str
    start_date: int
    end_date: int | None
    status: ActivityStatus
    description: str | None
    created_at: int
    updated_at: int

    model_config = {"from_attributes": True}


class ActivityHistoryItem(BaseModel):
    """Activity-management row, including request-backed pending creations."""

    id: int | None
    pending_request_id: int | None = None
    user_id: int
    project_id: int | None
    project_name: str | None
    position: str
    start_date: int
    end_date: int | None
    status: ActivityHistoryStatus
    description: str | None
    created_at: int
    updated_at: int


class ActivityHistoryAdminItem(ActivityHistoryItem):
    user: UserBrief
