# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

This project uses **uv** for Python package management (Python 3.11+) and **mise** for version management. Do not use pip or other package managers.

## Common Commands

### Setup and Dependencies
```bash
uv sync --dev
uv run pre-commit install
```

### Running the Application
```bash
# Start MySQL database (required)
docker compose up -d

# Run FastAPI server
uv run uvicorn app.main:app --reload
```

Access at: http://127.0.0.1:8000/docs (Swagger UI)

### Code Quality
```bash
# Run all pre-commit checks (recommended)
uv run pre-commit run --all-files

# Apply formatting
uv run black .
uv run isort .
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_file.py -v

# Run single test function
uv run pytest tests/test_file.py::test_function_name -v
```

### Database Reset (dev only)
```bash
uv run python -c "from app.config.database import Base, engine; from app import models; Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)"
```

## Architecture

### Layered Architecture
```
Routes (HTTP) -> Deps (Auth/Authorization) -> Services (Business Logic) -> Models (Data)
```

- **Routes** (`app/routes/`): FastAPI routers defining API endpoints. Handle HTTP concerns only.
- **Deps** (`app/deps/`): FastAPI dependencies for authentication and authorization.
- **Services** (`app/services/`): Business logic. Accept db session and data, return entities or None.
- **Models** (`app/models/`): SQLAlchemy ORM models.
- **Schemas** (`app/schemas/`): Pydantic models for request/response validation.
- **Exceptions** (`app/exceptions.py`): Structured application errors.

### Data Models

**Core Entities:**
- `User`: Member with profile, qualification level, admin flag. Soft-delete via `deleted_at`.
- `Project`: Projects with status (active/maintenance/ended).
- `ProjectMember`: Many-to-many linking Users to Projects with role (leader/member).
- `UserHistory`: Audit log tracking user events (qualification changes, project joins, etc.).

**Enums** (`app/models/enums.py`):
- `Qualification`: PENDING → ASSOCIATE → REGULAR → ACTIVE (membership levels)
- `ProjectStatus`: ACTIVE, MAINTENANCE, ENDED
- `MemberRole`: LEADER, MEMBER
- `HistoryAction`: Audit event types

### Authorization Pattern

Auth dependencies in `app/deps/auth.py`:
```python
get_current_user       # Any authenticated user
require_associate      # qualification != PENDING
require_regular        # qualification in (REGULAR, ACTIVE)
require_admin          # is_admin == True
```

Project-level auth in `app/deps/project.py`:
```python
require_leader_or_admin  # Must be project leader or admin
```

### Exception Handling

Custom exceptions in `app/exceptions.py` extend `AppError`:
```python
class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400)
```

Common exceptions: `UnauthorizedError`, `ForbiddenError`, `NotFoundError`, `LastLeaderError`, etc.

Global exception handler in `app/main.py` converts to JSON: `{"ok": False, "error": code, "message": ...}`

### Response Format

All API responses follow: `{"ok": boolean, "data": ..., "message": ...}`

Use `Response[T]` from schemas to wrap return data in routes.

### Time Handling

All timestamps are Unix epoch integers (BigInteger). Use `int(time.time())` for current time.

### Adding New Features

1. **New endpoint**: Schema → Service → Route → Register in `app/main.py`
2. **New model**: Create in `app/models/`, import in `app/models/__init__.py`
3. **Schema changes**: Use `model_config = {"from_attributes": True}` for ORM compatibility

### Testing

Tests use SQLite in-memory database. Available fixtures in `tests/conftest.py`:
- `db`: Fresh database session
- `client`: TestClient with test db
- User fixtures: `pending_user`, `associate_user`, `regular_user`, `active_user`, `admin_user`
- Token fixtures: `pending_token`, `associate_token`, `regular_token`, `active_token`, `admin_token`

### Configuration

**Local (ENV=local)**: Uses `.env` file for `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`

**Dev/Prod (ENV=dev/prod)**: Fetches credentials from AWS Secrets Manager via `AWS_SECRET_NAME`
