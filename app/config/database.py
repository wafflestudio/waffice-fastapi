# app/config/database.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

# ----------------------------------------------------------------------
# Load .env
# ----------------------------------------------------------------------
load_dotenv()

DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "")
DB_ECHO = os.getenv("DB_ECHO", "false").lower() in ("1", "true", "yes", "on")

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
        echo=DB_ECHO,
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
# IMPORTANT: Use Base from app.models (do NOT declare a new Base here)
# ----------------------------------------------------------------------
# This ensures a single metadata is used across the whole app.
from app.models import Base  # noqa: E402


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

    We import app.models to ensure all model modules are loaded and
    registered on Base.metadata before calling create_all().
    """
    import app.models  # noqa: F401  (side effect: registers all ORM models)

    Base.metadata.create_all(bind=Engine)


def drop_all() -> None:
    """
    (Optional) Drop all tables. Useful for local/dev resets.
    """
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=Engine)
