# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

This project uses **uv** for Python package management (Python 3.11+) and **mise** for version management. Do not use pip or other package managers.

## Common Commands

### Setup and Dependencies
```bash
# Install and sync dependencies
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install
```

### Running the Application
```bash
# Start MySQL database (required)
docker compose up -d

# Run FastAPI server
uv run uvicorn app.main:app --reload

# Run on specific host/port
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Access at:
- Swagger UI: http://127.0.0.1:8000/docs
- Redoc: http://127.0.0.1:8000/redoc

### Code Quality
```bash
# Run all pre-commit checks
uv run pre-commit run --all-files

# Check formatting (Linux/Mac: ./lint.sh, Windows: lint.bat)
uv run black --check .
uv run isort --check-only .

# Apply formatting
uv run black .
uv run isort .
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_file.py

# Run with verbose output
uv run pytest -v
```

### Database Operations
```bash
# Reset database (dev only) - drops and recreates all tables
uv run python -c "from app.config.database import Base, engine; from app import models; Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)"
```

## Architecture

### Layered Architecture Pattern
The codebase follows a 3-layer architecture:

```
Routes (HTTP) -> Controllers (Business Logic) -> Models (Data Access)
```

- **Routes** (`app/routes/`): Define API endpoints using FastAPI routers. Handle HTTP concerns (request/response, status codes). Use dependency injection for database sessions.

- **Controllers** (`app/controllers/`): Contain business logic. Accept database session and validated data. Return data or None (not HTTP exceptions).

- **Models** (`app/models/`): SQLAlchemy ORM models defining database schema and relationships.

- **Schemas** (`app/schemas/`): Pydantic models for request/response validation and serialization.

- **Config** (`app/config/`): Database connection and configuration setup.

### Key Components

**Database Session Management**:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
Use `db: Session = Depends(get_db)` in route functions for automatic session injection and cleanup.

**Data Models**:
- `User`: Main entity with profile, privileges, timestamps. Has one-to-many relationship with UserHistory (cascade delete).
- `UserPending`: Users awaiting approval/enrollment. Independent table with no relationships.
- `UserHistory`: Tracks user events (join, left, discipline, project changes). Many-to-one relationship with User.

**Time Handling**: All timestamps are stored as Unix epoch timestamps (BigInteger). Use `int(time.time())` for current time.

**Response Format**: All API responses follow `{"ok": boolean, ...}` format. Controllers return data or None; routes convert to appropriate HTTP responses.

**Error Handling**:
- Controllers return None for "not found" cases
- Routes convert None to HTTPException with appropriate status codes
- IntegrityError from SQLAlchemy indicates constraint violations (e.g., duplicate keys)

### Configuration

#### Environment Variables

**Local Development (ENV=local)**:
- `ENV`: Set to `local` for local development
- `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`: MySQL connection details
- Default: localhost:3306 when MySQL runs in Docker and FastAPI on host

**Dev/Production Deployment (ENV=dev or ENV=prod)**:
- `ENV`: Set to `dev` or `prod`
- `AWS_SECRET_NAME`: Name of the AWS Secrets Manager secret containing DB credentials
- `AWS_REGION`: AWS region (default: ap-northeast-2)

**AWS Secrets Manager Secret Format**:
The secret should be stored as JSON with the following structure:
```json
{
  "username": "db_user",
  "password": "db_password",
  "host": "db.example.com",
  "port": "3306",
  "dbname": "database_name"
}
```

**Database Connection**:
- Local: Uses `.env` file values directly
- Dev/Prod: Fetches credentials from AWS Secrets Manager via boto3
- Connection string: `mysql+pymysql://USER:PASSWORD@HOST:PORT/DB_NAME`

### Adding New Features

1. **Add new endpoint**:
   - Create/update Pydantic schema in `app/schemas/`
   - Add controller function in `app/controllers/`
   - Add route in `app/routes/` with appropriate decorators and Depends(get_db)
   - Register router in `app/main.py` if creating new route file

2. **Add new model**:
   - Create model class inheriting from Base in `app/models/`
   - Import model in `app/models/__init__.py`
   - Tables auto-create on app startup via `Base.metadata.create_all(bind=engine)`
   - For production, use Alembic migrations (alembic package is installed)

3. **Modify existing model**:
   - Update SQLAlchemy model in `app/models/`
   - For dev: reset database using command above
   - For production: create Alembic migration

### Important Patterns

- Enum types (UserType, UserPrivilege, UserHistoryType) defined in schemas ensure type safety
- Use `model_config = {"from_attributes": True}` in Pydantic response schemas for SQLAlchemy ORM compatibility
- User enrollment is atomic: moves record from UserPending to User table (insert + delete)
- Pre-commit hooks automatically run Black, isort, and Ruff before commits
