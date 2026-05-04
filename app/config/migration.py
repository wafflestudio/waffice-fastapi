"""Migration runner with MySQL distributed locking for safe multi-pod deployments."""

import logging
from contextlib import contextmanager

from sqlalchemy import text

from alembic import command
from alembic.config import Config
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
        logger.info(
            "Attempting to acquire MySQL advisory lock '%s' (timeout=%ds)",
            lock_name,
            timeout,
        )
        try:
            result = conn.execute(
                text("SELECT GET_LOCK(:lock_name, :timeout)"),
                {"lock_name": lock_name, "timeout": timeout},
            )
        except Exception as e:
            logger.exception("Error executing GET_LOCK: %s", e)
            raise

        try:
            acquired = result.scalar()
        except Exception:
            logger.exception("Failed to read GET_LOCK result")
            raise

        if acquired != 1:
            logger.error(
                "Failed to acquire migration lock '%s' within %ds. Another migration may be in progress.",
                lock_name,
                timeout,
            )
            raise RuntimeError(
                f"Failed to acquire migration lock '{lock_name}' within {timeout}s. "
                "Another migration may be in progress."
            )

        logger.info("Acquired migration lock: '%s'", lock_name)

        try:
            yield
        finally:
            # Release the lock
            conn.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": lock_name},
            )
            logger.info("Released migration lock: '%s'", lock_name)


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
    print("\n▶ Starting database migrations...")
    logger.info("Starting database migrations")
    try:
        logger.info("Importing models")
        import app.models  # noqa: F401
    except Exception:
        logger.exception("Failed to import app.models")
        raise

    logger.info("Creating Alembic config")
    alembic_cfg = Config("alembic.ini")

    with mysql_lock(LOCK_NAME, LOCK_TIMEOUT):
        logger.info("Running Alembic upgrade")
        try:
            command.upgrade(alembic_cfg, "head")
        except Exception as e:
            logger.exception("Alembic upgrade failed: %s", e)
            raise
        logger.info("Database migrations completed successfully")
        print("✓ Database migrations completed successfully\n")
