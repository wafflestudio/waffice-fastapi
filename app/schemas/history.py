from pydantic import BaseModel

from app.models.enums import HistoryAction
from app.schemas.user import UserBrief


class HistoryDetail(BaseModel):
    id: int
    action: HistoryAction
    payload: dict
    actor: UserBrief | None
    created_at: int

    model_config = {"from_attributes": True}
