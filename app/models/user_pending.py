# /models/user_pending.py

"""
UserPending Model Definition
============================

- Author: KMSstudio
- Description:
    Represents pending users who applied for membership but are not yet approved.
"""

from sqlalchemy import BigInteger, Column, String

from app.config.database import Base


class UserPending(Base):
    __tablename__ = "user_pending"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    google_id = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), nullable=False)
    name = Column(String(128), nullable=False)
    profile_picture = Column(String(512))
    ctime = Column(BigInteger, nullable=False)
