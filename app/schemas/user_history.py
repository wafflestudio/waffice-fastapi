# app/schemas/user_history.py
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


class UserHistoryType(str, Enum):
    join = "join"
    left = "left"
    discipline = "discipline"
    project_join = "project_join"
    project_left = "project_left"


class UserHistoryBase(BaseModel):
    user_id: int
    event_type: UserHistoryType
    description: Optional[str] = None
    prev_json: Optional[Dict[str, Any]] = None
    curr_json: Optional[Dict[str, Any]] = None
    operated_by: Optional[int] = None


class UserHistoryCreate(UserHistoryBase):
    pass


class UserHistory(UserHistoryBase):
    id: int
    ctime: datetime

    model_config = {"from_attributes": True}
