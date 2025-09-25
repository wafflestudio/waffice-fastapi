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
    준회원 = "준회원"
    정회원 = "정회원"
    활동회원 = "활동회원"


# User
class User(Base):
    __tablename__ = "user"

    userid = Column(BigInteger, primary_key=True, autoincrement=True)
    google_id = Column(String(255), nullable=False, unique=True)
    type = Column(Enum(UserType), nullable=False)
    privilege = Column(Enum(UserPrivilege), nullable=False)
    admin = Column(Integer, nullable=False, default=0)  # 0/1/2
    atime = Column(BigInteger, nullable=False)
    ctime = Column(BigInteger, nullable=False)
    mtime = Column(BigInteger, nullable=False)
    time_quit = Column(BigInteger, nullable=True)
    time_stop = Column(BigInteger, nullable=True)
    info_phonecall = Column(String(32))
    info_email = Column(String(255))
    info_major = Column(String(128))
    info_cardinal = Column(String(32))
    info_position = Column(String(128))
    info_work = Column(String(128))
    info_introduce = Column(Text)
    info_sns1 = Column(String(255))
    info_sns2 = Column(String(255))
    info_sns3 = Column(String(255))
    info_sns4 = Column(String(255))
    id_github = Column(String(255))
    id_slack = Column(String(255))
    receive_email = Column(Boolean, default=True)
    receive_sms = Column(Boolean, default=True)

    histories = relationship(
        "UserHistory", back_populates="user", cascade="all, delete-orphan"
    )
