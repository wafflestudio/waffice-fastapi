from pydantic import BaseModel, Field

from app.models.enums import HistoryAction
from app.schemas.user import UserBrief


class HistoryDetail(BaseModel):
    """
    Audit log entry tracking user events.

    History actions include qualification changes, admin grants/revokes,
    and project membership changes.
    """

    id: int = Field(description="Unique history entry identifier")
    action: HistoryAction = Field(
        description=(
            "Type of action recorded. Values: "
            "'qualification_changed' (membership level changed), "
            "'admin_granted' (admin privileges given), "
            "'admin_revoked' (admin privileges removed), "
            "'project_joined' (added to project), "
            "'project_left' (removed from project), "
            "'project_role_changed' (role changed within project)"
        )
    )
    payload: dict = Field(
        description="Additional action-specific data. Structure varies by action type.",
        examples=[
            {"from": "pending", "to": "associate"},
            {"project_id": 1, "role": "member"},
        ],
    )
    actor: UserBrief | None = Field(
        description="User who performed the action. Null for system actions."
    )
    created_at: int = Field(
        description="Unix timestamp when the action occurred",
        examples=[1706745600],
    )

    model_config = {"from_attributes": True}
