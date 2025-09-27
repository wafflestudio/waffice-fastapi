# /models/user.py

"""
User Model Definition
=====================

This module defines the SQLAlchemy ORM model for the `user` table.

- Author: KMSstudio
- Description:
    Represents a user in the system with attributes such as
    google_id, type, privilege, contact info, and other metadata.
    Provides relationship to UserHistory for tracking user changes/events.
"""

import enum

from sqlalchemy import BigInteger, Boolean, Column, Enum, Integer, String, Text
from sqlalchemy.orm import relationship

from app.config.database import Base


# ENUM
class UserType(enum.Enum):
    programmer = "programmer"
    designer = "designer"


class UserPrivilege(enum.Enum):
    associate = "associate"
    regular = "regular"
    active = "active"


# User
class User(Base):
    __tablename__ = "user"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    google_id = Column(String(255), nullable=False, unique=True)
    type = Column(Enum(UserType), nullable=False)
    privilege = Column(Enum(UserPrivilege), nullable=False)
    admin = Column(Integer, nullable=False, default=0)  # 0/1/2
    atime = Column(BigInteger, nullable=False)
    ctime = Column(BigInteger, nullable=False)
    mtime = Column(BigInteger, nullable=False)
    time_quit = Column(BigInteger, nullable=True)
    time_stop = Column(BigInteger, nullable=True)
    profile_phone = Column(String(32))
    profile_email = Column(String(255))
    profile_major = Column(String(128))
    profile_cardinal = Column(String(32))
    profile_position = Column(String(128))
    profile_work = Column(String(128))
    profile_intro = Column(Text)
    profile_sns1 = Column(String(255))
    profile_sns2 = Column(String(255))
    profile_sns3 = Column(String(255))
    profile_sns4 = Column(String(255))
    id_github = Column(String(255))
    id_slack = Column(String(255))
    receive_email = Column(Boolean, default=True)
    receive_sms = Column(Boolean, default=True)

    histories = relationship(
        "UserHistory", back_populates="user", cascade="all, delete-orphan"
    )
