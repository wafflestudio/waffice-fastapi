# app/models/project.py
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

ProjectStatus = ("active", "maintenance", "ended")
ProjectMemberRole = ("leader", "member")


class Project(Base):
    __tablename__ = "waffice_projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        SAEnum(*ProjectStatus, name="project_status"),
        nullable=False,
        default=ProjectStatus[0],
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    ctime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    mtime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    websites: Mapped[list["ProjectWebsite"]] = relationship(
        "ProjectWebsite",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name!r}, status={self.status})>"


class ProjectWebsite(Base):
    __tablename__ = "waffice_project_websites"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("waffice_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[Optional[str]] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    kind: Mapped[Optional[str]] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    mtime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="websites",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProjectWebsite(project_id={self.project_id}, url={self.url[:50]}...)>"


class ProjectMember(Base):
    __tablename__ = "waffice_project_members"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("waffice_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("waffice_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        SAEnum(*ProjectMemberRole, name="project_member_role"),
        nullable=False,
        default=ProjectMemberRole[1],  # member
    )
    position: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    ctime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    mtime: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
    )
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="members",
        lazy="selectin",
    )
    user = relationship(
        "WafficeUser",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectMember(project_id={self.project_id}, user_id={self.user_id}, "
            f"role={self.role}, position={self.position})>"
        )
