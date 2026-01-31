"""Migration runner with MySQL distributed locking for safe multi-pod deployments."""

import logging
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config.database import Engine

logger = logging.getLogger(__name__)

LOCK_NAME = "alembic_migration"
LOCK_TIMEOUT = 30  # seconds


@contextmanager
def mysql_lock(lock_name: str, timeout: int):
    """
    Acquire a MySQL advisory lock for the duration of the context.

    This prevents race conditions when multiple pods try to run migrations
    simultaneously during deployment.
    """
    with Engine.connect() as conn:
        # Try to acquire the lock
        result = conn.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout)"),
            {"lock_name": lock_name, "timeout": timeout},
        )
        acquired = result.scalar()

        if acquired != 1:
            raise RuntimeError(
                f"Failed to acquire migration lock '{lock_name}' within {timeout}s. "
                "Another migration may be in progress."
            )

        logger.info(f"Acquired migration lock: {lock_name}")

        try:
            yield
        finally:
            # Release the lock
            conn.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": lock_name},
            )
            logger.info(f"Released migration lock: {lock_name}")


def run_migrations() -> None:
    """
    Run all pending Alembic migrations with distributed locking.

    This function:
    1. Acquires a MySQL advisory lock to prevent concurrent migrations
    2. Runs `alembic upgrade head` programmatically
    3. Releases the lock when complete

    Safe to call from multiple pods during deployment - only one will
    run migrations while others wait.
    """
    # Import models to ensure they're registered
    import app.models  # noqa: F401

    alembic_cfg = Config("alembic.ini")

    with mysql_lock(LOCK_NAME, LOCK_TIMEOUT):
        logger.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
