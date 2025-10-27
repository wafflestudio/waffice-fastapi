# /config/database.py

import json
import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
        raise ValueError(
            f"AWS_SECRET_NAME must be set for environment: {ENV}"
        )

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

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

engine = create_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
