# app/models/user.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

UserType = ("programmer", "designer")
UserPrivilege = ("associate", "regular", "active")


class WafficeUser(Base):
    __tablename__ = "waffice_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(
        SAEnum(*UserType, name="user_type"), nullable=False
    )
    privilege: Mapped[str] = mapped_column(
        SAEnum(*UserPrivilege, name="user_privilege"), nullable=False
    )

    admin: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ctime: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    mtime: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    time_quit: Mapped[Optional[datetime]] = mapped_column(DateTime)
    time_stop: Mapped[Optional[datetime]] = mapped_column(DateTime)

    profile_phone: Mapped[Optional[str]] = mapped_column(String(32))
    profile_email: Mapped[Optional[str]] = mapped_column(String(255))
    profile_major: Mapped[Optional[str]] = mapped_column(String(128))
    profile_cardinal: Mapped[Optional[str]] = mapped_column(String(32))
    profile_position: Mapped[Optional[str]] = mapped_column(String(128))
    profile_work: Mapped[Optional[str]] = mapped_column(String(128))
    profile_intro: Mapped[Optional[str]] = mapped_column(Text)
    id_github: Mapped[Optional[str]] = mapped_column(String(255))
    id_slack: Mapped[Optional[str]] = mapped_column(String(255))
    receive_email: Mapped[bool] = mapped_column(Boolean, default=True)
    receive_sms: Mapped[bool] = mapped_column(Boolean, default=True)

    # 🔧 FK를 명시해서 모호성 제거
    histories = relationship(
        "UserHistory",
        back_populates="user",
        foreign_keys="UserHistory.user_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    acted_histories = relationship(
        "UserHistory",
        back_populates="actor",
        foreign_keys="UserHistory.operated_by",
        lazy="selectin",
    )

    links = relationship(
        "UserLink",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="UserLink.ord",
    )
