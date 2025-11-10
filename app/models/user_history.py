from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class UserHistory(Base):
    __tablename__ = "waffice_user_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("waffice_users.id", ondelete="CASCADE"), nullable=False
    )
    operated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("waffice_users.id"), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    prev_json: Mapped[Optional[dict]] = mapped_column(JSON)
    curr_json: Mapped[Optional[dict]] = mapped_column(JSON)

    ctime: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    user = relationship(
        "WafficeUser",
        back_populates="histories",
        foreign_keys=[user_id],
    )
    actor = relationship(
        "WafficeUser",
        back_populates="acted_histories",
        foreign_keys=[operated_by],
    )
