# app/config/database.py
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Generator

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

# ----------------------------------------------------------------------
# Load .env
# ----------------------------------------------------------------------
load_dotenv()

ENV = os.getenv("ENV", "local")  # local, dev, prod


def get_db_credentials():
    """Get database credentials from AWS Secrets Manager or environment variables."""
    if ENV == "local":
        # Use local environment variables
        return {
            "username": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "3306"),
            "dbname": os.getenv("DB_NAME"),
        }

    # For dev/prod: use AWS Secrets Manager
    secret_name = os.getenv("AWS_SECRET_NAME")
    region_name = os.getenv("AWS_REGION", "ap-northeast-2")

    if not secret_name:
        raise ValueError(f"AWS_SECRET_NAME must be set for environment: {ENV}")

    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise Exception(f"Failed to retrieve secret from AWS Secrets Manager: {e}")

    secret = json.loads(get_secret_value_response["SecretString"])

    return {
        "username": secret.get("username"),
        "password": secret.get("password"),
        "host": secret.get("host", "localhost"),
        "port": secret.get("port", "3306"),
        "dbname": secret.get("dbname"),
    }

# Get database credentials
db_creds = get_db_credentials()

DB_USER = db_creds["username"]
DB_PASSWORD = db_creds["password"]
DB_HOST = db_creds["host"]
DB_PORT = db_creds["port"]
DB_NAME = db_creds["dbname"]

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
