# app/config/database.py
from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config.secrets import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

# ----------------------------------------------------------------------
# Build DATABASE URL (PyMySQL)
# ----------------------------------------------------------------------
DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=DB_USER or None,
    password=DB_PASSWORD or None,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME or None,
    query={"charset": "utf8mb4"},
)


# ----------------------------------------------------------------------
# Engine (singleton)
# ----------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_engine():
    """
    Return a singleton SQLAlchemy Engine.
    Use pool_pre_ping & pool_recycle for stable MySQL connections.
    """
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_recycle=280,
    )
    return engine


# Create global Engine and Session factory
Engine = get_engine()
SessionLocal = sessionmaker(
    bind=Engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)

# ----------------------------------------------------------------------
# Declarative Base
# ----------------------------------------------------------------------
Base = declarative_base()


# ----------------------------------------------------------------------
# FastAPI dependency
# ----------------------------------------------------------------------
def get_db() -> Generator:
    """
    FastAPI Depends(get_db) helper.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------------------------------------------------
# Schema helpers
# ----------------------------------------------------------------------
def create_all() -> None:
    """
    Create all tables defined in app.models.*
    """
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=Engine)


def drop_all() -> None:
    """
    (Optional) Drop all tables. Useful for local/dev resets.
    """
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=Engine)
