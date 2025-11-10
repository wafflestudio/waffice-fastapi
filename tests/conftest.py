# tests/conftest.py
import os
import sys

# Get absolute path to the project root (where "app" exists)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
