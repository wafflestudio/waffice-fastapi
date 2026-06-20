from pydantic import BaseModel, Field

from app.models.enums import ActivityStatus


class ActivityCreateRequest(BaseModel):
    team_name: str = Field(description="Team or organization name", max_length=200)
    position: str = Field(description="Role or position in the team", max_length=100)
    start_date: int = Field(description="Activity start date (Unix timestamp)")
    end_date: int | None = Field(
        default=None, description="Activity end date (Unix timestamp). Null if ongoing."
    )
    status: ActivityStatus = Field(
        default=ActivityStatus.ACTIVE, description="활동 중 or 비활동"
    )
    description: str | None = Field(default=None, description="Additional notes")


class ActivityUpdateRequest(BaseModel):
    team_name: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=100)
    start_date: int | None = Field(default=None)
    end_date: int | None = Field(default=None)
    status: ActivityStatus | None = Field(default=None)
    description: str | None = Field(default=None)


class ActivityDetail(BaseModel):
    id: int
    user_id: int
    team_name: str
    position: str
    start_date: int
    end_date: int | None
    status: ActivityStatus
    description: str | None
    created_at: int
    updated_at: int

    model_config = {"from_attributes": True}
