# Waffice Project FastAPI repository

> 최초작성일 2025.09.26  
> 최신개정일 2025.09.26  
> 작성자 [23기 강명석](mailto:tomskang@naver.com)  
> 최신개정자 [23기 강명석](mailto:tomskang@naver.com)  

`waffice-fastapi` 레포지토리는 와플 internals 프로젝트의 일부입니다.

## Environment Setup (using uv)

This project uses [uv](https://github.com/astral-sh/uv), a new Python package manager that provides fast and simple workflows. [Reference](https://www.0x00.kr/development/python/python-uv-simple-usage-and-example).

### Install and sync dependencies
```bash
uv sync --dev
```

### VSCode integration
After running `uv sync`, set the Python interpreter in VSCode to:
- Windows: `.venv/Scripts/python.exe`
- Linux/Mac: `.venv/bin/python`

## Code Formatting and Linting

This project uses **Black** and **isort** for formatting and linting.  
All configurations are defined in `pyproject.toml` and `.pre-commit-config.yaml`.

### Pre-commit Hook
Install the pre-commit hook to run Black, isort, and Ruff automatically before every commit:
```bash
uv run pre-commit install --hook-type post-commit
```

Manual run for all files:
```bash
uv run pre-commit run --all-files
```

## Lint Scripts

Linting scripts are available at the project root.

### Windows (`lint.bat`)
```bat
uv run black --check .
uv run isort --check-only .
```

### Linux/Mac (`lint.sh`)
```bash
uv run black --check .
uv run isort --check-only .
```

- These scripts only run in **check mode** and do not modify files.  
- If there are violations, they will exit with an error.  
- To apply fixes manually, run `black .` and `isort .` on root directory.
