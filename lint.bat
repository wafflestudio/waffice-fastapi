@echo off
REM ================================
REM  Python Lint & Format Check
REM ================================

echo Running Black (check only)...
uv run black --check .

echo Running isort (check only)...
uv run isort --check-only .

echo.
echo =======================================
echo   Lint check completed!
echo =======================================
pause
