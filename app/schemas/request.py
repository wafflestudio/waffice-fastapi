from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ActivityStatus, ApprovalStatus, MemberRole
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief


class RequestKind(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class RequestScope(str, Enum):
    RECEIVED = "received"
    SENT = "sent"
    ALL = "all"


class RequestStatusFilter(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL = "all"


class RequestKindFilter(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ALL = "all"


class ActivityPayload(BaseModel):
    project_id: int
    position: MemberRole
    start_date: int
    end_date: int | None = None
    status: ActivityStatus = ActivityStatus.ACTIVE
    description: str | None = None


class ActivityPatchPayload(BaseModel):
    position: MemberRole | None = None
    start_date: int | None = None
    end_date: int | None = None
    status: ActivityStatus | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one editable field is required")
        return self


class RequestReviewBody(BaseModel):
    reviewer_patch: dict | None = None
    final: dict | None = None
    diff: dict | None = None


class ApprovalRequestBody(BaseModel):
    request_kind: RequestKind
    target_user_id: int
    activity_id: int | None = None
    before: dict | None = None
    after: ActivityPayload | None = None
    reason: str = Field(min_length=1, max_length=2000)
    review: RequestReviewBody = Field(default_factory=RequestReviewBody)


class ApprovalRequestCreateRequest(BaseModel):
    request_kind: RequestKind
    target_user_id: int | None = None
    activity_id: int | None = None
    after: ActivityPayload | None = None
    reason: str = Field(min_length=1, max_length=2000)
    reviewer_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request_body(self):
        if (
            self.request_kind in (RequestKind.UPDATE, RequestKind.DELETE)
            and self.activity_id is None
        ):
            raise ValueError("activity_id is required for update/delete requests")
        if (
            self.request_kind in (RequestKind.CREATE, RequestKind.UPDATE)
            and self.after is None
        ):
            raise ValueError("after is required for create/update requests")
        if self.request_kind == RequestKind.DELETE and self.after is not None:
            raise ValueError("after must be omitted for delete requests")
        return self


class ApprovalRequestUpdateRequest(BaseModel):
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    after: ActivityPayload | None = None
    reviewer_ids: list[int] | None = None


class ApprovalReviewRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalReviewWithEditsRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
    reviewer_patch: ActivityPatchPayload


class ApprovalRejectRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class RequestReviewerDetail(BaseModel):
    id: int
    user: UserBrief

    model_config = {"from_attributes": True}


class ApprovalRequestListItem(BaseModel):
    id: int
    requester: UserBrief
    request_kind: RequestKind
    status: ApprovalStatus
    created_at: int
    reviewed_at: int | None


class ApprovalRequestDetail(BaseModel):
    id: int
    requester: UserBrief
    project: ProjectBrief | None
    reviewed_by: UserBrief | None
    reviewers: list[RequestReviewerDetail]
    status: ApprovalStatus
    body: ApprovalRequestBody
    review_comment: str | None
    created_at: int
    updated_at: int
    reviewed_at: int | None
