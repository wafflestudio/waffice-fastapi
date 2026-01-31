# Waffice FastAPI

Waffle internals 프로젝트의 백엔드 API 서버입니다.

## 기술 스택

- **Python 3.11+** with **uv** (패키지 관리)
- **FastAPI** (웹 프레임워크)
- **SQLAlchemy 2.0** (ORM)
- **Alembic** (DB 마이그레이션)
- **MySQL** (데이터베이스)

## 시작하기

### 요구사항

- Docker & Docker Compose
- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

### 설치

```bash
# 의존성 설치
uv sync --dev

# pre-commit hook 설치
uv run pre-commit install
```

### 환경변수 설정

`.env.example`을 복사하여 `.env` 파일을 생성합니다.

```env
DB_USER=myuser
DB_PASSWORD=mypass
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=mydb
```

### 실행

```bash
# MySQL 실행
docker compose up -d

# FastAPI 서버 실행
uv run uvicorn app.main:app --reload
```

API 문서: http://127.0.0.1:8000/docs

## 개발

### 코드 포맷팅

```bash
# 전체 검사 및 자동 수정
uv run pre-commit run --all-files
```

### 테스트

```bash
# 전체 테스트
uv run pytest

# 특정 테스트 파일
uv run pytest tests/test_file.py -v
```

### DB 마이그레이션

```bash
# 마이그레이션 생성
uv run alembic revision --autogenerate -m "description"

# 마이그레이션 적용
uv run alembic upgrade head

# 롤백
uv run alembic downgrade -1
```

### DB 초기화 (개발용)

```bash
docker compose down -v && docker compose up -d
```

## 프로젝트 구조

```
app/
├── main.py           # FastAPI 앱 진입점
├── config/           # 설정 (DB, 마이그레이션)
├── models/           # SQLAlchemy 모델
├── schemas/          # Pydantic 스키마
├── routes/           # API 라우터
├── services/         # 비즈니스 로직
├── deps/             # 인증/인가 의존성
├── utils/            # 유틸리티
└── exceptions.py     # 커스텀 예외
```
