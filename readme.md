# Waffice Project FastAPI repository

> 최초작성일 2025.09.26  
> 최신개정일 2025.11.13  
> 작성자 [23기 강명석](mailto:tomskang@naver.com)  
> 최신개정자 [23기 강명석](mailto:tomskang@naver.com)  

`waffice-fastapi` 레포지토리는 와플 internals 프로젝트의 일부입니다.

## 1. Environment Setup (using uv)

This project uses [uv](https://github.com/astral-sh/uv), a new Python package manager that provides fast and simple workflows. [Reference](https://www.0x00.kr/development/python/python-uv-simple-usage-and-example).

Specifically, tools below are required.
- Docker & Docker Compose
- Python 3.11+ and **uv**

### 1.1. Install and sync dependencies
```bash
uv sync --dev
```

### 1.2. VSCode integration
After running `uv sync`, set the Python interpreter in VSCode to:
- Windows: `.venv/Scripts/python.exe`
- Linux/Mac: `.venv/bin/python`

## 2. Code Formatting and Linting

This project uses **Black** and **isort** for formatting and linting.  
All configurations are defined in `pyproject.toml` and `.pre-commit-config.yaml`.

### 2.1 Pre-commit Hook
Install the pre-commit hook to run Black, isort, and Ruff automatically before every commit:
```bash
uv run pre-commit install
```

Manual run for all files:
```bash
uv run pre-commit run --all-files
```

### 2.2. Lint Scripts

Linting scripts are available at the project root.

#### 2.2.a. Windows (`lint.bat`)
```bat
uv run black --check .
uv run isort --check-only .
```

#### 2.2.b Lint Scripts - Linux/Mac (`lint.sh`)
```bash
uv run black --check .
uv run isort --check-only .
```

- These scripts only run in **check mode** and do not modify files.  
- If there are violations, they will exit with an error.  
- To apply fixes manually, run `black .` and `isort .` on root directory.

## 3. Execute project

This section explains how to run **MySQL (via Docker Compose)** and start the FastAPI app with **uv**.  
Before you start, make sure you’ve completed **1.1 Install and sync dependencies**.  
  
### 3.1. Prepare environment variables
Create `.env` (or copy from `.env.example`) at the project root:

```env
DB_USER=myuser
DB_PASSWORD=mypass
DB_HOST=127.0.0.1   # If FastAPI runs on host and MySQL runs in Docker
DB_PORT=3306
DB_NAME=mydb
```

### 3.2. Start MySQL via Docker Compose
From the project root (where `docker-compose.yml` exists):

```bash
docker compose up -d
docker compose logs -f
```

`logs -f` is optional: Check readiness.
Wait until you see: "ready for connections"

Optional: verify DB port is open on host:
```bash
nc -zv 127.0.0.1 3306
tnc 127.0.0.1 -port 3306
```

### 3.3. Run the FastAPI app
```bash
uv run uvicorn app.main:app --reload
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- Swagger UI: http://127.0.0.1:8000/docs  
- Redoc: http://127.0.0.1:8000/redoc

## 4. Error handling

### 4.1. Quick health checks
Create a pending user:
```bash
curl -X POST http://127.0.0.1:8000/api/user/create \
  -H "Content-Type: application/json" \
  -d '{"google_id":"test-sub","email":"test@example.com","name":"홍길동","profile_picture":null}'
```

Enroll the pending user (replace `pending_id`):
```bash
curl -X POST http://127.0.0.1:8000/api/user/enroll \
  -H "Content-Type: application/json" \
  -d '{"pending_id":1,"type":"programmer","privilege":"associate"}'
```

Fetch user info:
```bash
curl "http://127.0.0.1:8000/api/user/info?userid=1"
```

### 4.2. Reset database **(dev only)**
Drop & recreate tables quickly (from project root):
```bash
uv run python -c "from app.config.database import Base, engine; from app import models; Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)"
```

Or drop/recreate the whole DB inside the MySQL container:
```bash
# Open MySQL shell inside container (replace 'mydb' with your container name)
docker exec -it mydb mysql -uroot -p

-- Then in MySQL:
DROP DATABASE IF EXISTS mydb;
CREATE DATABASE mydb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4.3. Troubleshooting
- **Access denied for user 'myuser'@'x.x.x.x' (1045)**  
  - Ensure the user exists and is allowed from host `%` (dev)  
  - Check `.env` credentials and `DB_HOST=127.0.0.1` when FastAPI runs on host
  - If needed (inside MySQL):
    ```sql
    CREATE USER 'myuser'@'%' IDENTIFIED BY 'mypass';
    GRANT ALL PRIVILEGES ON mydb.* TO 'myuser'@'%';
    FLUSH PRIVILEGES;
    ```

- **Lost connection to MySQL server during query (2013)**  
  - MySQL may not be ready; wait until logs show “ready for connections”  
  - Add a short retry on app startup or try again after a few seconds

- **Port already in use**  
  - Another MySQL is running on 3306; stop it or change the compose port mapping
  - On Windows: check with `netstat -ano | findstr 3306`
