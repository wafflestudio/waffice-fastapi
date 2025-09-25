# /models/user_history.py

"""
UserHistory Model Definition
============================

This module defines the SQLAlchemy ORM model for the `user_history` table.

- Author: KMSstudio
- Description:
    Tracks events and changes related to a user, such as account creation,
    withdrawal, disciplinary actions, and project membership history.
    Provides a relationship back to the User model for ownership.
"""

import enum

from sqlalchemy import BigInteger, Column, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.config.database import Base


class UserHistoryType(enum.Enum):
    join = "join"
    left = "left"
    discipline = "discipline"
    project_join = "project_join"
    project_left = "project_left"


class UserHistory(Base):
    __tablename__ = "user_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    userid = Column(
        BigInteger, ForeignKey("user.userid", ondelete="CASCADE"), nullable=False
    )
    type = Column(Enum(UserHistoryType), nullable=False)
    description = Column(Text)
    curr_privilege = Column(
        Enum("associate", "regular", "active", name="curr_privilege_enum"),
        nullable=True,
    )
    curr_time_stop = Column(BigInteger, nullable=True)
    prec_privilege = Column(
        Enum("associate", "regular", "active", name="prec_privilege_enum"),
        nullable=True,
    )
    prec_time_stop = Column(BigInteger, nullable=True)

    user = relationship("User", back_populates="histories")
