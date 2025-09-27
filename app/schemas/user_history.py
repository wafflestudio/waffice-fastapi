# schemas/user_history.py

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class UserHistoryType(str, Enum):
    join = "join"
    left = "left"
    discipline = "discipline"
    project_join = "project_join"
    project_left = "project_left"


class UserHistoryBase(BaseModel):
    userid: int
    type: UserHistoryType
    description: Optional[str] = None
    curr_privilege: Optional[str] = None
    curr_time_stop: Optional[int] = None
    prev_privilege: Optional[str] = None
    prev_time_stop: Optional[int] = None


class UserHistoryCreate(UserHistoryBase):
    pass


class UserHistory(UserHistoryBase):
    id: int

    model_config = {"from_attributes": True}
