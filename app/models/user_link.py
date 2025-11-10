# app/models/user_link.py
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class UserLink(Base):
    __tablename__ = "waffice_user_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("waffice_users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ord: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctime: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    mtime: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    user = relationship("WafficeUser", back_populates="links")

    __table_args__ = (
        Index(
            "uq_waff_user_links_unique",
            "user_id",
            "kind",
            "url",
            unique=True,
            mysql_length={"url": 255},
        ),
    )

    def __repr__(self) -> str:
        return f"<UserLink(user_id={self.user_id}, kind={self.kind}, url={self.url[:50]}...)>"
