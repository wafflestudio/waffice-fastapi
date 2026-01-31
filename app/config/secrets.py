# app/config/secrets.py
"""
Centralized secrets management.
- Local: reads from environment variables (.env file)
- Dev/Prod: reads from AWS Secrets Manager
"""

import json
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV") or os.getenv("SPRING_PROFILES_ACTIVE") or "local"


@lru_cache(maxsize=1)
def _get_secrets_from_aws() -> dict[str, Any]:
    """Fetch all secrets from AWS Secrets Manager."""
    secret_name = f"{ENV}/waffice-server"
    region_name = os.getenv("AWS_REGION", "ap-northeast-2")

    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise RuntimeError(f"Failed to retrieve secrets from AWS: {e}")

    return json.loads(response["SecretString"])


@lru_cache(maxsize=1)
def get_secrets() -> dict[str, Any]:
    """
    Get all application secrets.
    - Local: from environment variables
    - Dev/Prod: from AWS Secrets Manager
    """
    if ENV == "local":
        # Local environment: use .env file
        return {
            # Database
            "username": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "3306"),
            "dbname": os.getenv("DB_NAME"),
            # Google OAuth
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", ""),
            "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "GOOGLE_REDIRECT_URI": os.getenv(
                "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
            ),
            # Frontend
            "FRONTEND_ORIGIN": os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
            # JWT / App
            "APP_SECRET_KEY": os.getenv("APP_SECRET_KEY", "insecure-dev-only-key"),
            "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY", "insecure-dev-only-key"),
            "JWT_EXPIRE_HOURS": os.getenv("JWT_EXPIRE_HOURS", "24"),
        }

    # Dev/Prod: fetch from AWS Secrets Manager
    return _get_secrets_from_aws()


# Convenience accessors
secrets = get_secrets()

# Database
DB_USER = secrets.get("username")
DB_PASSWORD = secrets.get("password")
DB_HOST = secrets.get("host", "localhost")
DB_PORT = secrets.get("port", "3306")
DB_NAME = secrets.get("dbname")

# Google OAuth
GOOGLE_CLIENT_ID = secrets.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = secrets.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = secrets.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)

# Frontend
FRONTEND_ORIGIN = secrets.get("FRONTEND_ORIGIN", "http://localhost:3000")

# JWT / App
APP_SECRET_KEY = secrets.get("APP_SECRET_KEY", "insecure-dev-only-key")
JWT_SECRET_KEY = secrets.get("JWT_SECRET_KEY") or APP_SECRET_KEY
JWT_EXPIRE_HOURS = int(secrets.get("JWT_EXPIRE_HOURS", "24"))
