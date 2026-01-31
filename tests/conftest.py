import os
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.database import Base, get_db
from app.main import app
from app.models import Qualification, User
from app.services import UserService

# Use SQLite in-memory for tests
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("APP_SECRET_KEY", "change-me"))
JWT_ALGORITHM = "HS256"


def get_test_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db() -> Session:
    """Create a fresh database for each test"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create a test client with the test database"""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_access_token(user_id: int, email: str, google_id: str | None = None) -> str:
    """Helper to create JWT tokens for testing"""
    now = time.time()
    exp = now + timedelta(hours=24).total_seconds()

    payload = {
        "user_id": user_id,
        "email": email,
        "google_id": google_id,
        "iat": int(now),
        "exp": int(exp),
        "sub": str(user_id),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@pytest.fixture
def pending_user(db: Session) -> User:
    """Create a pending user for testing"""
    user = UserService.create(
        db,
        email="pending@example.com",
        name="Pending User",
        generation="26",
        qualification=Qualification.PENDING,
        google_id="pending_google_id",
    )
    return user


@pytest.fixture
def associate_user(db: Session) -> User:
    """Create an associate user for testing"""
    user = UserService.create(
        db,
        email="associate@example.com",
        name="Associate User",
        generation="26",
        qualification=Qualification.ASSOCIATE,
        google_id="associate_google_id",
    )
    return user


@pytest.fixture
def regular_user(db: Session) -> User:
    """Create a regular user for testing"""
    user = UserService.create(
        db,
        email="regular@example.com",
        name="Regular User",
        generation="26",
        qualification=Qualification.REGULAR,
        google_id="regular_google_id",
    )
    return user


@pytest.fixture
def active_user(db: Session) -> User:
    """Create an active user for testing"""
    user = UserService.create(
        db,
        email="active@example.com",
        name="Active User",
        generation="26",
        qualification=Qualification.ACTIVE,
        google_id="active_google_id",
    )
    return user


@pytest.fixture
def admin_user(db: Session) -> User:
    """Create an admin user for testing"""
    user = UserService.create(
        db,
        email="admin@example.com",
        name="Admin User",
        generation="26",
        qualification=Qualification.ACTIVE,
        is_admin=True,
        google_id="admin_google_id",
    )
    return user


@pytest.fixture
def pending_token(pending_user: User) -> str:
    """Create JWT token for pending user"""
    return create_access_token(
        pending_user.id, pending_user.email, pending_user.google_id
    )


@pytest.fixture
def associate_token(associate_user: User) -> str:
    """Create JWT token for associate user"""
    return create_access_token(
        associate_user.id, associate_user.email, associate_user.google_id
    )


@pytest.fixture
def regular_token(regular_user: User) -> str:
    """Create JWT token for regular user"""
    return create_access_token(
        regular_user.id, regular_user.email, regular_user.google_id
    )


@pytest.fixture
def active_token(active_user: User) -> str:
    """Create JWT token for active user"""
    return create_access_token(active_user.id, active_user.email, active_user.google_id)


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """Create JWT token for admin user"""
    return create_access_token(admin_user.id, admin_user.email, admin_user.google_id)
