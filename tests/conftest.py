# tests/conftest.py

import os
import sys

# Get absolute path to the project root (where "app" exists)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import pytest

from app.config.database import create_all, drop_all  # type: ignore


@pytest.fixture(autouse=True)
def _reset_db():
    """각 테스트 전에 DB를 drop/create 해서 독립성 유지"""
    drop_all()
    create_all()
    yield
