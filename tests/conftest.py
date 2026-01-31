import atexit
import os
import time
from datetime import timedelta

from testcontainers.mysql import MySqlContainer

# ----------------------------------------------------------------------
# Start testcontainers and set env vars BEFORE any app imports
# ----------------------------------------------------------------------
_mysql = MySqlContainer(
    image="mysql:8.0",
    username="test",
    password="test",
    dbname="testdb",
)
_mysql.start()

# Register cleanup
atexit.register(_mysql.stop)

# Set environment variables for database.py
os.environ["DB_HOST"] = _mysql.get_container_host_ip()
os.environ["DB_PORT"] = str(_mysql.get_exposed_port(3306))
os.environ["DB_USER"] = "test"
os.environ["DB_PASSWORD"] = "test"
os.environ["DB_NAME"] = "testdb"

# ----------------------------------------------------------------------
# Now import app modules (they will use the env vars above)
# ----------------------------------------------------------------------
import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config.database import Base, Engine, get_db
from app.main import app
from app.models import Qualification, User
from app.services import UserService

# JWT config (must match app/deps/auth.py default)
JWT_SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("APP_SECRET_KEY")
    or "insecure-dev-only-key"
)
JWT_ALGORITHM = "HS256"


@pytest.fixture(scope="session")
def engine():
    """Return the app's configured engine (connected to testcontainers)."""
    return Engine


@pytest.fixture(scope="session")
def tables(engine):
    """Tables are created by migrations in app lifespan. Just yield."""
    # Migrations already ran when app was imported (via lifespan)
    yield
    # Cleanup is optional since container will be destroyed anyway


@pytest.fixture(scope="function")
def db(engine, tables) -> Session:
    """Create a fresh database session for each test with table truncation."""
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()

    yield session

    session.close()

    # Truncate all tables after each test for isolation
    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE {table.name}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()


@pytest.fixture(scope="function")
def client(db):
    """Create a test client with the test database."""

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
    """Helper to create JWT tokens for testing."""
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
    """Create a pending user for testing."""
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
    """Create an associate user for testing."""
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
    """Create a regular user for testing."""
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
    """Create an active user for testing."""
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
    """Create an admin user for testing."""
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
    """Create JWT token for pending user."""
    return create_access_token(
        pending_user.id, pending_user.email, pending_user.google_id
    )


@pytest.fixture
def associate_token(associate_user: User) -> str:
    """Create JWT token for associate user."""
    return create_access_token(
        associate_user.id, associate_user.email, associate_user.google_id
    )


@pytest.fixture
def regular_token(regular_user: User) -> str:
    """Create JWT token for regular user."""
    return create_access_token(
        regular_user.id, regular_user.email, regular_user.google_id
    )


@pytest.fixture
def active_token(active_user: User) -> str:
    """Create JWT token for active user."""
    return create_access_token(active_user.id, active_user.email, active_user.google_id)


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """Create JWT token for admin user."""
    return create_access_token(admin_user.id, admin_user.email, admin_user.google_id)
