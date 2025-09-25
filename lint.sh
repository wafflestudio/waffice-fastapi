#!/bin/bash
# ================================
#  Python Lint & Format Check
# ================================

set -e

echo "Running Black (check only)..."
uv run black --check .

echo "Running isort (check only)..."
uv run isort --check-only .

echo
echo "======================================="
echo "  Lint & format check completed!"
echo "======================================="
